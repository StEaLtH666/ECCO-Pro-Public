# Production Mode and Geek Mode (offline proof on the ECCO Intelligence tab)

Status: the first offline proof, complete on both sides (the data side and the shell, merged and run against each other). Nothing here is deployed, installed or registered; nothing touches Home
Assistant, the dongle, the inverter or InfluxDB; no firmware is involved. The proof is one representative tab, the standalone ECCO
Intelligence SHADOW view, so that the idea can be judged before any other tab is converted.

This document records the design, the invariants both halves of the proof must keep, the acceptance cases, how to apply the shell
to another tab, what the proof does not do, and the integration steps that are left to the owner. The numbers quoted are those of
this change; the generated ledger (`docs/product-ui/GEEK_MODE_COVERAGE_LEDGER_intelligence.md`) is the authority for the current ones. Section 12
records what running the two halves against each other found.

## 1. The idea

Each tab has two presentations of the same data:

- **Production Mode** is what a normal user sees: calm and simple. For the Intelligence tab it is the existing, unchanged
  ECCO Intelligence card and its pause tile.
- **Geek Mode** shows EVERY available non-secret data point of the tab: every sensor, attribute, diagnostic, timestamp, derived
  value, assumption, limit, code and provenance, grouped, collapsible, searchable and filterable, with a redacted raw-attributes
  inspector, descriptions, units, update ages and source identifiers, and copy/export of non-secret diagnostics.

Both modes read ONE snapshot of `hass.states` through ONE adapter and carry IDENTICAL safety permissions. The mode is a
PRESENTATION toggle. It is not the ECCO Manual / Assisted / Automatic authority and has nothing to do with it: switching it never
starts or stops Intelligence, never enables ASSISTED or AUTONOMOUS, never alters Manual control authority, never writes a register
or a helper, never cancels an armed session and never calls a service. Safety-critical alerts, recovery state and
owner-action-needed status stay visible in both modes.

```
                 hass.states (read only)
                        |
                 one snapshot  <----  the catalogue (data, inline in the card config)
                        |
     +------------------+-------------------+
     |                                      |
 Production view                        Geek view
 (the existing cards,                   (inspector rows built from the catalogue
  passed through unchanged)              and from discovery; redacted; windowed)
     |                                      |
     +------------------+-------------------+
                        |
              safety alert strip (always, both modes; derived from the catalogue's alerts)
```

The shell is the reusable part: ONE per-view mode switch and ONE adapter, parameterised by a catalogue. A new tab is a new
catalogue plus its existing card as a child, not a second dashboard implementation. The shell itself is `frontend/ecco-mode-shell/ecco-mode-shell.js` (one file, no dependency). This change delivers both halves: the data
side (the catalogue, the information coverage ledger, the synthetic fixtures and the Python tests) and the shell, its node tests, its
preview and the example dashboard; section 12 records how they were joined.

## 2. What this change contains (new files only)

| File | What it is |
|---|---|
| `tools/geek_mode_coverage.py` | computes the available universe FROM CODE, builds the catalogue and the ledger, validates the catalogue against the schema, compares with the live shape; `--check` regenerates and compares |
| `tools/geek_mode_texts_intelligence.py` | the plain-words texts (titles, descriptions, alerts, exceptions); data only; the tool refuses a missing or an orphan text |
| `tools/gen_geek_fixtures.py` | the synthetic state fixtures, built from the real contract builders; `--check` |
| `frontend/ecco-mode-shell/catalogue/intelligence.catalogue.json` | the catalogue, schema `ecco-geek-catalogue/1` |
| `frontend/ecco-mode-shell/catalogue/intelligence.ledger.json` | the ledger in machine form, schema `ecco-geek-ledger/1` |
| `frontend/ecco-mode-shell/catalogue/live-shape.intelligence.json` | the live shape listing (names, types, sizes; no value), the input of the live comparison |
| `frontend/ecco-mode-shell/test/fixtures/intelligence.states.*.json`, `noise.states.json`, `intelligence.states.meta.json` | synthetic fixtures for the card tests |
| `docs/product-ui/GEEK_MODE_COVERAGE_LEDGER_intelligence.md` | the human-readable ledger (generated) |
| `docs/product-ui/PRODUCTION_GEEK_MODE.md` | this document |
| `tools/tests/test_geek_mode_*.py`, `tools/tests/_geek_scratch.py` | six suites (catalogue, coverage, ledger, fixtures, privacy, example) and their shared helper |
| `frontend/ecco-mode-shell/ecco-mode-shell.js` | the shell: the mode switch, the one adapter, the alert strip, the Geek inspector, the redactor |
| `frontend/ecco-mode-shell/test/*.test.mjs`, `test/minidom.mjs`, `test/helpers.mjs`, `test/secrets.mjs` | the node tests (core, element, coverage, static, mutations, and `real-catalogue.test.mjs` against the real catalogue, ledger and fixtures) |
| `frontend/ecco-mode-shell/test/fixtures/{mini,hostile}*.json` | the card's own small synthetic fixtures |
| `frontend/ecco-mode-shell/preview/index.html` | the offline preview: the real card and the real Intelligence card on the real catalogue and fixtures |
| `frontend/ecco-mode-shell/examples/intelligence-modes.yaml`, `test/test_example_dashboard.py` | the example dashboard (the existing cards, wrapped; the real catalogue included) and its Python check |
| `frontend/ecco-mode-shell/README.md` | how to use, test and preview the shell |

Every file is new: no existing, frozen, pinned, sealed or deployed file is edited.

Regenerate, in this order (the ledger records the hash of the fixtures, so the fixtures come first):

```
python -I -B -X utf8 tools/gen_geek_fixtures.py
python -I -B -X utf8 tools/geek_mode_coverage.py
python -I -B -X utf8 tools/gen_geek_fixtures.py --check
python -I -B -X utf8 tools/geek_mode_coverage.py --check
```

## 3. The interfaces

### 3.1 The catalogue (`ecco-geek-catalogue/1`)

Produced by the Python side, consumed by the card, INLINE in the card configuration (normally through a YAML `!include` of the JSON
file; JSON is valid YAML and the generated file is written so that a YAML loader reads it identically, which a test proves). The card
fetches nothing. The catalogue is data, never code, and the card must tolerate unknown extra keys.

```
{ schema: "ecco-geek-catalogue/1", view_id, title, contract,
  groups:     [ {id, title, order, description} ],
  sources:    [ {id, entity_id, group, title, description, priority, unit, expected_update_s, stale_after_s, origin,
                 attributes: [ {name, description, unit, priority} ] } ],
  discover:   { entity_prefixes: [...], group, exclude_entity_ids: [...] },
  alerts:     [ {id, severity, entity_id, when, text, action} ],
  exceptions: [ {id, what, reason, note} ],
  redaction:  { extra_key_patterns: [...] } }
```

- `priority` is `headline` (what normal users care about), `normal` or `obscure` (diagnostics). Headline first, obscure reachable.
- `origin` is `integration`, `package` or `dashboard`. Intelligence has no dashboard-origin source: the dashboard defines no data of
  its own (a check proves every entity it references is catalogued).
- `expected_update_s` and `stale_after_s` are set only for sources whose `last_updated` is expected to move: the eleven integration
  entities (60 s, the integration's tick; 1200 s, the package watchdog's maximum age, computed from the integration's constants and
  cross-checked against the watchdog template). Package helpers and automations change only when something happens, so they are
  never age-judged (null).
- An attribute name is an attribute, or ONE dotted path into the first nesting level of a dict attribute (for example
  `advice.target_soc_pct`, `decisions.I-D1`). Deeper levels are shown in the raw (redacted) inspector under the parent and are not
  counted separately. A list attribute (`blockers`, `reason_codes`, `input_ages`) is one row; the keys of its rows are in its
  description.
- Alert conditions `when` are exactly one of `{state_in: [..]}`, `{state_not_in: [..]}`, `{state_outside: [..]}`, `{unavailable: true}`,
  `{attribute: name, in: [..]}`, `{attribute: name, not_in: [..]}` (the last two forms and `state_outside` were added in review round 1,
  section 13: `not_in` is STRICT, so the text "true" is not the boolean true; `state_outside` fires only for a state that is up and not listed). The intended meaning of `{unavailable: true}` is: the entity's state is `unavailable`, or the entity
  is missing from `hass.states` (a declared entity that is missing is as bad as an unavailable one; it must not hide an alert).
  An `in` list may mix booleans and texts (`applies_nothing` is listed as false, "false" and "False") so a strict or a stringified
  comparison both match. The shell pins both readings in `frontend/ecco-mode-shell/test/real-catalogue.test.mjs`: the state `unavailable`
  or a missing entity fires an `unavailable` alert; an `unknown` state does not (it is reported as a condition that cannot be checked, so a
  restart does not raise a critical alert), while a listed `unknown` state fires its own alert.
- `discover` lists `<domain>.ecco_intel_` prefixes. An entity that matches a prefix and is not in `sources` appears in the group
  `discovered` by itself, with no hand-designed card. A lookalike (the frozen V1 prototype's `ecco_intelligence_` family, a name that
  merely contains the prefix, a domain that is not listed) never appears.
- `redaction.extra_key_patterns` are lower-case key fragments added to the card's own defaults. For Intelligence they are the
  integration's own diagnostics redaction list (computed from `diagnostics.py`): `config_hash`, `entities`, `git_sha`, `latitude`,
  `longitude`. Two rows therefore exist with their VALUE withheld: `git_sha` and `config_hash`.
- `exceptions` are things that are not Home Assistant states (or must not be shown), each with a reason from `secret`, `privacy`,
  `unsupported_source`, `not_exposed_in_states` and a note on what showing it would take. Nothing is excepted for convenience.

### 3.2 The ledger (`ecco-geek-ledger/1`)

The auditable information coverage ledger: for every source and attribute, its id, origin, group, priority, `COVERED`, the honesty
states it can take, what declared it (contract list, block keys, advisor source, package YAML, Home Assistant standard), whether the
Production card's read lists name it, its live status, live type and size, whether its value is withheld, and which fixtures
exercise it. Every exception follows with its reason. A row id is the source id, or `<source id>#<attribute name>`; that is the rule
the card's coverage test uses. The ledger records the sha256 of the catalogue, of the live shape listing and of every fixture, so
the card-side coverage test and this ledger cannot drift apart without `--check` failing.

Live comparison vocabulary: `PRESENT_LIVE`; `NOT_PRESENT_LIVE` (declared, absent from the live entity; every one at present is a
conditional shape, for example the OK advice keys of an item that is not OK live); `NOT_CHECKED_LIVE` (outside the listing's name
filter: the reserve helper `input_number.ecco_advisory_reserve_raise_pct` does not contain `ecco_intel`); `UNDECLARED` (present
live, declared by no code or package: a finding the owner must see; none at present).

### 3.3 The fixtures

Each file is a map `entity_id -> {state, attributes, last_changed, last_updated}` as `hass.states` holds it (a state is always a
text, a missing figure is `unknown`, a flag is `on`/`off`; Home Assistant's standard attributes are included). Every value is
synthetic (fictional 2030 timestamps, invented figures). `intelligence.states.meta.json` gives the clock to read each fixture at.

| Fixture | Reference clock | What it is |
|---|---|---|
| `healthy` | publish + 30 s | every item and forecast OK, a verified tariff, a value, a plan: the richest result |
| `mixed` | publish + 30 s | two items OK, one NO_ADVICE, one INSUFFICIENT_DATA, data quality DEGRADED, tariff unverified |
| `stale` | publish + 30 s | the contract's STALE fixture; `last_good` carries the history |
| `unavailable` | publish + 30 s | every integration entity unavailable; the watchdog off |
| `self-test-failed` | publish + 30 s | the contract's SELF_TEST_FAILED fixture; the alert automation has run |
| `paused` | publish + 30 s | the contract's PAUSED fixture; the pause switch on; the watchdog on |
| `watchdog-stale` | publish + 55 min | a healthy result nobody refreshed: older than `stale_after_s`, past `valid_until`, watchdog off, alert run |
| `extras` | publish + 30 s | healthy plus an undeclared attribute, four new `ecco_intel_` entities to discover (one carries a `simulated` flag) and five lookalikes that must not be discovered |
| `noise` | n/a | 300+ unrelated entities and twelve secret-looking DECOYS for the redaction tests |

The healthy, mixed and watchdog-stale fixtures are built with the real contract constructors (`assemble_envelope` and
`to_entity_payloads`); stale, paused and self-test-failed are exactly the contract fixtures' payloads; the healthy fixture's
attribute names equal those the running Home Assistant exposes, entity by entity. The decoys are kept below the repository's own
secret-scanner thresholds so they can be committed (a JWT-shaped text with short segments, a documentation-range address, `.invalid`
hosts); the card's own tests build the full-size private-address, MAC and long-token shapes at test time, so no secret-shaped text is
ever committed.

## 4. Safety invariants

The proof keeps these, and each has a test on the data side or the card side:

1. READ ONLY. The shell reads `hass.states` and nothing else: no service call, websocket message, REST call, fetch, event, or
   storage. A hass stub whose every function throws must run every interaction (switch, search, filter, expand, page, copy, export,
   raw view) without a throw, and no storage is touched.
2. The mode never changes authority. It is not ECCO Manual / Assisted / Automatic; it never writes; it never cancels a session.
3. IDENTICAL permissions in both modes. Production-only and always-visible child cards are passed through unchanged. A child that
   is visible in Geek Mode with any write action is rejected (`validateChildCards`, an allowlist of card types since review round 1).
   Geek Mode grants no extra write permission, exposes no installer-only write and bypasses no backend confirmation. The standard
   `hass-more-info` event is itself a write path for a writable domain (its dialog has a slider, a toggle, Run or Install), so Geek Mode
   dispatches it only for a sensor, a binary sensor or an event; every other row offers the entity id to copy.
4. Each tab defaults to Production on entry and on reload; a switch in one view never changes another; if Home Assistant caching or
   navigation keeps a component alive, the mode is reset to Production on entry.
5. The safety alert strip is derived from the catalogue's alerts, shows every alert condition identically in both modes and cannot
   be hidden by either. It is built from what is valid even when the catalogue is partly malformed.
6. Fail closed. An unknown schema or a malformed source gives a visible error, never a silent fallback, and the strip still shows.
7. Honest inventory. A value is never invented and never shown as live when it is not: unavailable, unknown, stale (older than
   `stale_after_s`), declared-but-missing (NOT_MEASURED), simulated and unverified each have a word and an icon, never colour alone.
8. Secrets and private data are never surfaced because they exist: token, password, secret, api key, authorization, bearer,
   credential, private key, webhook, cookie and session keys; JWT-like strings; long hex or base64 blobs; URLs with userinfo or token
   queries; webhook paths (the id is the credential); IP and MAC addresses; latitude, longitude and location keys; login names under a
   qualified key (`mqtt_user`, `db_login`); connection strings; the catalogue's extra patterns. They are
   withheld in rows, the raw inspector, the search index, copy and export, in nested values, and in key names that look secret.
9. Data is inert text. No element or attribute is ever created from data; markup, quotes, control and zero-width characters render as
   text.
10. Performance is bounded: one page of rows on first render, search over the snapshot within a stated budget, one changed entity
    updates one row, oversized attributes are truncated with a marker.
11. Accessibility: keyboard operable switch with visible focus and aria labels, 44 px targets, reduced motion respected, status never
    colour alone, no horizontal scroll at 375 px, light and dark.
12. New safe entities (the `ecco_intel_` prefix) are discoverable without another hand-designed card.

## 5. Acceptance cases AC1 to AC16

"This change" is the data side, proven by the Python suites. "Shell" is the card side (`frontend/ecco-mode-shell`), proven by the node tests,
which since the merge run against the very same catalogue, ledger and fixtures (`test/real-catalogue.test.mjs`); section 12 lists the results.

| AC | Behaviour | This change | Shell |
|---|---|---|---|
| AC1 | default Production on first render | - | first-render test |
| AC2 | a reload (a fresh element) is Production | - | fresh-element test |
| AC3 | enter, switch to Geek, leave (location-changed, disconnect, hidden, pagehide) and return: Production | - | one test per leave signal |
| AC4 | two shell instances never share or leak a mode | - | two-instance test |
| AC5 | every interaction makes zero calls; no storage | the catalogue and fixtures are plain data | throwing hass stub; static pin for storage; behavioural test |
| AC6 | the alert strip shows every alert identically in both modes, over unavailable and unknown | 19 alerts derived from the contract (every status and data-quality state alerted or listed as none, plus the four that mirror what the package watchdog needs); every alert names a catalogued entity; fixtures for each alert state (`stale`, `paused`, `self-test-failed`, `unavailable`, `watchdog-stale`); `test_geek_mode_catalogue.py` [3], `test_geek_mode_fixtures.py` [5] | parametrised over every alert and over unavailable and unknown states |
| AC7 | same data in Production and Geek | one catalogue, one fixture format | changing-hass test of the one adapter. Bound (section 14.2): in a burst of more than eight relevant updates in 500 ms the child cards still get every `hass` at once while the shell's snapshot (Geek rows, Production summary, alert strip) is coalesced into one rebuild at the end of the burst, so the two can differ for up to about 500 ms; a reused row may trail its age text by less than one second, never its status |
| AC8 | coverage: every non-excepted source has a row; every declared attribute is reachable; discovery adds only the prefix | the universe is computed from code; 17 sources, 344 attribute rows, all COVERED; row id rule; every declared path exercised by a fixture; `extras` and `noise` for discovery; `test_geek_mode_coverage.py` [1]-[3], `test_geek_mode_ledger.py` [2], [5] | the same assertions against the same catalogue and fixtures, with the ledger's row ids |
| AC9 | honesty: unavailable, unknown, stale, NOT_MEASURED and simulated labelled in words and icon; nothing fabricated | timing from the integration's constants; fixtures for unavailable, stale in time (`watchdog-stale`), unknown (`unknown` figures), declared-but-missing (non-OK shapes) and a `simulated` flag (`extras`) | label, icon and never-live tests |
| AC10 | redaction everywhere (rows, raw, search, copy, export, nested, key names) | the redaction patterns include the integration's own list; the `noise` decoys (token, password, JWT-shaped, webhook, address, coordinates, connection strings, URL token, blobs, nested secrets, key names) and the proof they are committable; `test_geek_mode_privacy.py` | hostile-fixture tests for each surface; the export bytes contain no secret |
| AC11 | search, filter, grouping, headline first, empty result | groups, priorities and descriptions in the catalogue | search and filter tests |
| AC12 | performance with 5000 entities | `noise` is 300+ entities | 5000 generated in the test |
| AC13 | markup and hostile text render inert | all texts are ASCII, no markup (a test); no hostile text is committed | hostile fixture built at test time |
| AC14 | accessibility and layout | - | keyboard, targets, reduced motion, 375 px |
| AC15 | the ledger equals a regeneration; every available source COVERED or EXCEPTION with a reason; the card-side coverage runs against the same catalogue and fixtures | `geek_mode_coverage.py --check`, `gen_geek_fixtures.py --check`, the ledger's sha256 binding of catalogue, live shape and fixtures; mutations; `test_geek_mode_ledger.py` | AC8 run against the same files |
| AC16 | authority: children passed through unchanged; `validateChildCards` rejects a Geek child with a write action; the example dashboard wraps the existing card and tile; a bad catalogue fails closed and the strip still shows | the catalogue validator and its negative controls (a catalogue the shell must also refuse); the alert list a partial catalogue still yields | child-card tests; example dashboard; fail-closed test |

Mutation tests on this side: a source dropped, an attribute dropped, an attribute invented, an undeclared attribute added to a
scratch copy of the contract (with and without its payload), an undeclared advice key, a new automation, a new entity, a new
diagnostics section, a changed description, an orphan text, a missing text, an unalerted status, a changed fixture, a changed
live shape: each fails with its own message.

## 6. Applying the shell to another tab

1. List the tab's data: the entities, helpers, automations and attributes its dashboard and card use, and where the code declares
   them (a contract, a package, an integration, a card read list).
2. Write a view module like `tools/geek_mode_coverage.py` computes for Intelligence: a function that COMPUTES the available universe
   from that code, and a texts module with the plain-words descriptions. Recommended next step before the second tab: split the tool
   into a generic core (schema validator, JSON layout, ledger, live comparison, Markdown, `--check`) and one small view module per
   tab (universe plus texts), so the second tab adds a module, not a copy.
3. Generate the catalogue, the ledger and the fixtures; run `--check` and the suites. Anything the code exposes that has no text, or
   a text for something that is gone, fails the build.
4. Take a live shape listing once (read only; names, types and sizes, no values) and run the comparison: `UNDECLARED` is a finding.
5. In the dashboard, wrap the tab's EXISTING card (and its controls) as children of the shell, Production-visible, with the
   catalogue included inline. Do not change the existing cards, helpers or dashboards.
6. Run the shell's tests against the new catalogue and fixtures (AC1 to AC16).

## 7. What the proof does not do

- It does not deploy, register or install anything, and it does not touch a running Home Assistant, the dongle, the inverter or
  InfluxDB. The one live read it used, a read-only shape listing, was taken separately and is committed without any value.
- It does not change the existing Intelligence card, package, integration, dashboard, manifest, changelog, version or any pinned or
  sealed file. It does not touch the running Intelligence acceptance.
- It does not run in a real Home Assistant. The shell was run in a node stand-in for the DOM and in headless Chrome against a stand-in `hass`;
  the real card helpers, the real `location-changed` and cache behaviour, the real theme variables and the real entities card and tile are
  not exercised.
- It does not show information that is not a Home Assistant state or attribute: the diagnostics download, the recorder history, the
  logs, the registries, the notifications, the scorecard database and the owner's site file are listed as exceptions, each with a
  note on what exposing it would take (a new read-only diagnostic entity is a contract change request).
- It does not generate the descriptions: they are written by hand and checked for presence and for orphans, not for wording.
- It does not prove the card-side behaviours with Python: those are proven by the node tests (CI runs no Node); the Python side pins the
  data, the ledger, the example and these documents.

## 8. Integration TODOs for the owner (nothing here was done)

Each needs an edit to a frozen, pinned, sealed or deployed file, or a live step with its own authorisation, so each is left to the
owner:

1. `deployment/ha-manifest.yaml`: a new manifest entry for the shell module, the catalogue file and (if the catalogue is included
   from the dashboard) the dashboard file that includes it; the deploy script copies only what the manifest names.
2. `CHANGELOG.md`: a line for the Production Mode / Geek Mode proof.
3. The scope chain and pin files (`registry/tests/_scope_chain.py` and the PEX scope files): an entry for the new directories
   `frontend/ecco-mode-shell`, `docs/product-ui` and the new tools and suites, if the chain is to cover them. `tools/validate_repo.py`
   and the offline suites were run with the new files and did not demand any edit to a pinned file.
4. Resource registration: add the shell as a Lovelace resource of type JavaScript module (Settings, Dashboards, Resources) after
   the file is copied under `/config/www/ecco/`, with a version query, exactly as the Intelligence card's one-time registration
   describes. Each step is reversible by removing the resource.
5. The catalogue placement: the file must be readable by the dashboard's `!include` (under `/config/ecco/`), and a dashboard that
   includes it is a new dashboard file with its own approved deploy step. A dashboard YAML edit takes effect on reload; a new
   `lovelace: dashboards:` entry needs a Home Assistant restart, which needs its own approval.
6. Assist exposure: Geek Mode reads `hass.states` in the browser and needs no voice-assistant exposure. Confirm in Settings, Voice
   assistants, Expose that the `ecco_intel_` entities stay as the owner wants them (the proof assumes none are exposed and changes
   nothing).
7. Decide whether the three alert automations' entity ids (derived by Home Assistant from their aliases, for example
   `automation.ecco_intel_alert_no_fresh_intelligence_result` for the automation whose unique id is `ecco_intel_alert_watchdog_stale`)
   are the ones to keep; the catalogue uses the live entity id and the unique id as the source id.

8. The shell's resource: the manifest entry of item 1 names `frontend/ecco-mode-shell/ecco-mode-shell.js`, and the dashboard that includes the
   catalogue must be able to read it (the example uses a path relative to the example; a deployed dashboard needs the catalogue next to it).
9. A Python pin suite for the shell's source under `tools/tests`, mirroring `tools/tests/test_intelligence_card.py` (CI runs no Node, so the
   node tests do not run in CI). `tools/tests/test_geek_mode_example.py` already pins the example, the ledger and these documents.
10. Decide whether the pause tile may stay hidden in Geek Mode (today it does: Geek Mode only shows, it never offers a control, so the tile
    lives in Production only; the always-visible cards must be read-only and the shell refuses any that is not).
11. Decide whether a `more-info` action on a WRITABLE entity should be refused in an `always` card, as Geek Mode's own rows now do (the agreed
    interface allows `more-info`; the dialog of a switch, helper, automation or script has write controls). Nothing in the example does this.
12. Review the shell's default custom-card list (`custom:ecco-intelligence-card`, read-only and pinned by its own suite). Another custom card,
    for example another ECCO card, enters an `always` region only if the dashboard names it in `allow_custom_cards` after checking it.

## 9. Known limits

- The universe is computed from code by reading the advisors' source (the dict literals of the recommendation, the shadow cycle's
  summaries) and the contract. If one of them is refactored the tool fails loudly (a finding), it never silently drops a key. A
  behavioural test runs one real SHADOW cycle and checks everything it publishes against the catalogue.
- Home Assistant's own attributes (`friendly_name`, `device_class`, `options`, `icon`, `editable`, an automation's `current`, `id`,
  `last_triggered`, `mode`) come from the integration classes, the package YAML and a small table of what Home Assistant adds per
  domain; the live shape listing is the net that catches a difference. The reserve helper's attributes are NOT confirmed live (it is
  outside the listing's name filter).
- The live shape listing is one capture (14 Nov 2026) with the measured ages, the total entity count and the other-prefix counts
  removed. It shows two item entities in a non-OK shape, so their OK-shape advice keys are `NOT_PRESENT_LIVE` (conditional); the
  fixtures exercise them. Run the comparison again after any contract change.
- While the integration is PAUSED it publishes once, so a paused system's entities legitimately age past `stale_after_s` (the
  watchdog accepts a PAUSED status of any age). A Geek row will then be labelled stale with its age; the Paused alert explains why.
- A contract-version mismatch ("output not recognised") could not be written with the first agreed `{attribute, in}` form. Review
  round 1 added `{attribute, not_in}` and `{state_outside}` to `ecco-geek-catalogue/1` (an addition: no existing form changed), and the
  catalogue now alerts on a mode other than SHADOW, an `applies_nothing` that is not strictly true, a contract version it does not know
  and an unrecognised status word (section 13).
- Attributes deeper than the first nesting level (for example `advice.reserve.*`, `value.baselines.*`) are in the raw inspector only.
  The `self_test` dictionary has check codes as keys, so its keys are data, shown in the raw view, not declared rows.
- The catalogue is about 90 KB and the ledger about 220 KB: the catalogue is inlined into a card configuration, which is fine for a
  proof; a larger tab may prefer a resource file the shell loads, which would be a change to the "the card fetches nothing" rule.
- The fixtures are read at their reference clock (`intelligence.states.meta.json`); a test that uses the wall clock will see every
  fixture as old.
- The Intelligence contract has no "simulated" flag: nothing it publishes is a simulation (SHADOW advice is real advice that is not
  applied). The `extras` fixture carries a `simulated: true` attribute on one new entity only so that the honesty state SIMULATED can
  be exercised; the attribute name is that fixture's convention, and the shell decides which attribute flags a simulation. The
  catalogue schema has no field for it, by design (the agreed schema is unchanged).
- The descriptions were written against the code and its docstrings; where the code is the only source (for example the plan block's
  `precharge_by`), the wording is cautious. Review them with the owner before the proof is shown to normal users.

- A timestamp more than five minutes in the future (clock skew between the browser and Home Assistant) is UNVERIFIED with no age (review
  round 1); a smaller skew is read as an age of 0. The fixtures are in 2030 and are read at their own reference clock, never the wall clock.
- The catalogue has no `{unavailable: true}` alert for the data-quality entity, so while that entity is unavailable the strip shows two
  'cannot check' lines for it (blocked and degraded) instead of one 'unavailable' line. Adding that alert is a catalogue text change.
- "Same data" is not "the same instant" (review round 2, section 14.2): in a burst of more than eight relevant updates in 500 ms the child cards
  get every `hass` at once while the shell's own snapshot (Geek rows, Production summary, alert strip) is coalesced into one rebuild at the end of the
  burst, so the two can differ for up to about 500 ms; and a reused row may trail its age text by less than a second, never its status.
- Nothing ran in a real Home Assistant: the alert automations' live entity ids, the reserve helper's attributes, the real card helpers and
  the real theme are confirmed from code, the one shape listing and headless Chrome only.
- The alert strip's visibility rests on four nets (review round 3, section 15.2): the pin of the whole stylesheet, the allowlist for rules that can reach the strip, the
  strict reader and the opt-in headless Chrome check. The first three read CSS text and cannot see a rule on a neighbour that overlaps the strip, nor two allowed colours
  that are unreadable together; the pin and the browser check do. The browser check runs two window sizes and two card widths at load and after the mode switch only,
  measures contrast from computed colours (nothing is behind the strip but an opaque surface), and is run by a person.
- The redactor is a heuristic net with an exceptions list (section 15.3 lists what it still shows: a coarse degrees-minutes-seconds position, a phone number, a post code,
  a chat-bot token inside a URL path, a very short webhook id, compact words such as `wifipassword`); `state_not_in` is fail-safe for a down entity and cannot express "quiet when down".

## 10. Findings for the owner, and deviations from the brief

Findings (also in the ledger's section 2 where the tool can compute them):

1. Nothing present live is UNDECLARED. One declared source is not covered by the live listing: the reserve helper
   `input_number.ecco_advisory_reserve_raise_pct` (the listing's filter was names containing `ecco_intel`): `NOT_CHECKED_LIVE`; its
   Home Assistant standard attributes are unconfirmed live.
2. The three alert automations' entity ids differ from their unique ids (Home Assistant derives them from the alias): the automation
   with unique id `ecco_intel_alert_watchdog_stale` is `automation.ecco_intel_alert_no_fresh_intelligence_result` live. The catalogue
   uses the live entity id, and the unique id inside the source id.
3. While PAUSED the integration publishes once, so a paused system's rows legitimately age past `stale_after_s`; see section 9.
4. The contract-version mismatch could not be written with the first agreed alert conditions; review round 1 added the forms for it (sections 9 and 13).
5. The meaning of `{unavailable: true}` and of a mixed-type `in` list is written in section 3.1; the shell now pins both readings (and had
   to be corrected to read them, see section 12).
6. 42 declared attributes are absent from the live listing, every one a conditional shape (the OK advice keys of the two items that
   are not OK live, the non-OK advice keys of the five that are OK, and `last_good.*` because `last_good` is empty live).

Deviations from the brief, all deliberate:

- The committed live shape copy is the listing without `age_s` (the measured age of each entity), `total_states` and
  `other_ecco_prefix_counts` (site counts), with a provenance note: the ages are measured values and the counts are site facts.
- `--shape` defaults to the committed copy (`--no-shape` turns the comparison off), so `--check` needs no argument.
- Fixtures: the six asked for, plus `mixed`, `extras` and the meta file. `healthy` is richer than the contract's `synthetic_ok`.
- The noise decoys stay below the repository's secret-scanner thresholds so they can be committed; the noise word list is neutral (an
  earlier list of room names contained the repository's private-area prefix literal and tripped `test_public_privacy.py`; found and
  fixed before the commit).
- The reserve helper is a 17th source; Home Assistant standard attributes are catalogued like any other attribute.
- The example dashboard was written with the shell (`frontend/ecco-mode-shell/examples/intelligence-modes.yaml`); section 6 describes how one wraps the existing card.
- The owner's private pattern scan of `tools/tests/test_public_privacy.py` (`ECCO_PRIVATE_PATTERNS`) was not applied: the variable is
  not set and the patterns live in the offline area, which was not read.

## 11. How the proof was checked (summary)

The data side: `python -I -B -X utf8 tools/tests/test_geek_mode_catalogue.py`, `..._coverage.py`, `..._ledger.py`, `..._fixtures.py`,
`..._privacy.py`, `..._example.py`; `tools/geek_mode_coverage.py --check`; `tools/gen_geek_fixtures.py --check`; `tools/validate_repo.py`; and
`tools/run_offline_tests.py --root tools/tests --parallel 4`.

The shell: in `frontend/ecco-mode-shell`, `node --test test/*.test.mjs` (the node suite, including the mutation proof) and
`python -I -B -X utf8 test/test_example_dashboard.py`; the preview in headless Chrome (section 12.4); and, opt-in since review round 3,
`node preview/check-strip.mjs` and `--selftest` (headless Chrome measures the alert strip in both modes, section 15.5).

## 12. Joining the two halves (what running them against each other found)

The two halves were built apart, from the same agreed interfaces, by two builders. They were merged (the data side's branch into the shell's
branch; both only added files, so there was no conflict) and the shell's node tests were then run against the REAL catalogue, the machine
ledger and every fixture (`frontend/ecco-mode-shell/test/real-catalogue.test.mjs`, 118 tests). No assertion was weakened: every difference
found was repaired in the card, the test or the data, and each repair has a test that fails without it.

### 12.1 What the first run found

1. **The real catalogue was refused by the card.** The critical `applies_nothing_false` alert lists its values as `false`, `"false"` and
   `"False"` (a mixed-type in-list, section 3.1); the card accepted texts only, so `validateCatalogue` returned an error, dropped the
   alert and the shell would have failed closed with no inventory. The card now accepts booleans in the list and matches a value strictly or as
   text. (Mutant `AC6-bool-in-list-rejected`.)
2. **A listed `unknown` state never fired.** `status_unknown` lists the state `unknown`; the card treated every `unknown` state as unreadable and
   reported "cannot check" instead. A listed state that is the state now fires, whatever it is. (Mutant `AC6-listed-down-state-silent`.)
3. **`{unavailable: true}` fired on `unknown`.** The catalogue's reading is "unavailable, or missing"; the card also fired the critical "not
   publishing" alert on an `unknown` state, which a Home Assistant restart can produce while the status is still unknown. An `unknown` state is now reported as a condition that
   cannot be checked, never as silence and never as the critical alert. (Mutants `AC6-unavailable-fires-on-unknown`,
   `AC6-unavailable-ignores-missing`.)
4. **Redundant lines.** One failed entity could raise its own alert and a "cannot check" line for every other alert on it. An alert that already
   says the entity is down now replaces those lines. (Mutant `AC6-redundant-lines-kept`.)
5. **A false positive in the card's own hygiene scan.** `static.test.mjs` read the noise fixture's two connection-string decoys
   (`scheme://synthetic:decoy@host.invalid`) as e-mail addresses. Only that exact shape is exempt now, and a new assertion fails any other URL
   with credentials anywhere in the folder, so the scan is stricter than before, not weaker.

Nothing was found the other way round: the ledger agrees with the card row for row, nothing present live is `UNDECLARED`, and the fixtures
exercise every declared attribute (section 12.2).

### 12.2 What the real-catalogue test proves

| Case | Proven on the real catalogue, ledger and fixtures |
|---|---|
| AC6 | every one of the 15 alerts of that step (19 now, section 13) fires in Production and in Geek Mode, with its text, its action, its severity and an icon, for every way its condition can hold (20 cases); with each alert's entity unavailable, unknown or missing the strip is never silently clear; each fixture raises exactly the alerts the documented readings give; the strip is outside both bodies and identical in both modes |
| AC7 | one hass object reaches the strip, the Production summary, the Geek rows and the child cards; the Geek rows are the one adapter's rows |
| AC8 | on all 8 fixtures of that step (9 now) every source has one row and every declared attribute is reachable; the four new `ecco_intel_` entities of the `extras` fixture are discovered with no new card and the five lookalikes never appear; 300+ noise entities change nothing; every exception is listed with its reason |
| AC9 | on all 8 fixtures every row says its status in words and an icon, an unavailable, unknown or missing source shows no value, a stale source is never also Live, the simulated entity is labelled Simulated |
| AC10 | all 11 decoy entities (token, password, JWT-shaped, webhook, address, coordinates, connection strings, URL token, blobs, nested secrets, key names) are withheld in rows, attributes, raw views, search, copy and both exports; the catalogue's own redaction list withholds `git_sha` and `config_hash` everywhere |
| AC11 | groups in catalogue order, headline first inside each group, discovered last; search reaches an obscure attribute and an undeclared one |
| AC12 | with 5000 extra entities one page is in the DOM, search is quick and one changed entity rebuilds one row |
| AC15 | the catalogue, the live shape and every fixture have the hash the ledger recorded; the ids the card can show are exactly the 361 ledger rows; on every fixture each ledger row has a card row, each attribute is present exactly when the ledger says the fixture shows it, every card row has a ledger row, the honesty vocabulary, the two withheld values and the 28 exceptions agree |

The other cases (AC1 to AC5, AC13, AC14, AC16) are proven by the card's own node tests (`core`, `element`, `static`), now with 86 mutants (78
of the card's and 8 added for the points above), every one killed. The one deliberate undeclared item the card lists is the `extras`
fixture's invented attribute; the keys of `self_test` are data under a declared parent (section 9).

### 12.3 Results of the runs

The numbers of the join step; the current runs are in section 13.3.

| Run | Result |
|---|---|
| `node --test test/*.test.mjs` (core 99, element 97, coverage 4, static 17, real-catalogue 118, mutation proof 88) | 423 of 423 pass; 86 of 86 mutants killed |
| `python -I -B -X utf8 test/test_example_dashboard.py` | all checks pass (YAML with the include tag, the include resolves to the real catalogue, the wrapped cards equal the existing dashboard's) |
| `tools/tests/test_geek_mode_{catalogue,coverage,ledger,fixtures,privacy,example}.py` | all pass |
| `tools/gen_geek_fixtures.py --check`, `tools/geek_mode_coverage.py --check` | both match a fresh regeneration |
| `tools/validate_repo.py` | PASSED, with no edit to any pinned file |
| `tools/run_offline_tests.py --root tools/tests`, `ecco_core/tests`, `health/tests` | 21 of 21, 6 of 6 and 2 of 2 |
| the tests of `home-assistant/tests`, `intelligence/tests` and `registry/tests` that read `frontend/` or `docs/` (47) | 45 pass; two fail for reasons outside this change (see below) |

The two exceptions: `registry/tests/test_rtc_policy.py` fails its check "a C++ compiler is available" (no compiler on this PC; the test asks for
`ECCO_CXX`), and `registry/tests/test_dump_to_grid_v1.py` passes when run as `python -B -X utf8 <file>` but cannot import its sibling helper under
`-I`. Neither reads anything this change touches.

### 12.4 The preview, captured

`frontend/ecco-mode-shell/preview/index.html` runs the real card and the real Intelligence card on the real catalogue and fixtures (fourteen
scenarios, light and dark, a width control). It was captured in headless Chrome at 1280 px and 375 px, Production and Geek Mode, light and
dark, plus the alert, stale, unavailable, discovery, decoy, large and invalid scenarios (17 captures, kept outside the repository). A layout
probe at 375 px over 42 combinations (7 fixtures or scenarios, light and dark, Production, Geek and Geek with every row and raw view open)
found the card exactly 375 px wide, no element outside it and no button, select or input below 44 px.

### 12.5 The recommendation, and what must be decided before the second tab

One per-view mode switch and one adapter (this shell), parameterised by one catalogue per view, never two dashboard implementations. Before
the second tab: split `tools/geek_mode_coverage.py` into a generic core and one view module per tab (section 6), decide the pause-tile
question (section 8, item 10), and review the descriptions with the owner (section 9). The decisions the owner still owns are the integration
steps of section 8, none of which was done.

## 13. Review round 1 (15 Nov 2026): findings and fixes

An independent review of the proof (the card, the tests and the data side, 40 mutants of its own and seven probes) found two MAJOR findings and
nine smaller ones. Each was reproduced first (a failing test, or a mutant that no test killed), then fixed, and each fix has a test that fails
without it (the new tests were run against the card as reviewed: 47 of them failed there, with the hostile-value tests that now also cover the
new edge shapes) and mutants that undo it (section 13.1). No existing assertion was weakened or removed; the few places where a test had to
move with the data are listed in section 13.4. Still the same rules: new files only, no pinned or deployed file edited, nothing live.

### 13.1 The findings and what was done

| # | Severity | Finding | Fix | Proof |
|---|---|---|---|---|
| 1 | MAJOR | Geek rows offered **Open in Home Assistant** for every domain. The dialog Home Assistant opens for an `input_number` (the reserve slider), an `automation` (enable, disable, Run) and an `input_boolean` (the pause toggle) has write controls that Production does not show, so Geek Mode gave an extra write path, against its own note "Geek Mode only shows". The same held for any future `button.`, `switch.`, `number.`, `select.` and `script.` entity under the discover prefix | the row control and the one `hass-more-info` dispatch both go through `canOpenMoreInfo`: only a sensor, a binary sensor or an event may be opened. Every other row offers **Copy entity id** and says why (`data-no-open-note`) | element test over every domain the real catalogue discovers (19 domains, 36 rows: 15 read-only offer the dialog, 21 others do not and none dispatches); a direct test of the dispatch with 23 malformed or writable ids; mutants `AC16-open-*` (4) |
| 2 | MAJOR | A stylesheet rule such as `.shell[data-mode=geek] .alerts{display:none}` hid the alert strip in Geek Mode and no test failed: the AC6 tests looked at the hidden attribute and the DOM position, never at the stylesheet (reviewer mutant R10) | `static.test.mjs` now reads the stylesheet itself: the only selector that may name a mode is the switch thumb, and the only hiding declaration (display none, visibility, opacity, zero size, clip, off-screen offset, transparent text) allowed anywhere is the `[hidden]` rule. 24 hostile stylesheets are the reader's negative controls, each also appended to the real stylesheet | `static.test.mjs` (3 tests); mutants `AC6-css-*` (5), including R10 itself |
| 3 | MINOR | `setConfig` called again on the same element (Home Assistant does this when the dashboard configuration changes) left Geek Mode on | `setConfig` starts with the controller reset; the Geek surface is dropped with it | element test (twice in a row, and the switch still works after); static pin; mutants `AC3-setconfig-*` (including R34 forcing Geek) |
| 4 | MINOR | The package watchdog template turns OFF when the status entity itself says a mode other than SHADOW, an `applies_nothing` that is not strictly the boolean true, a contract it does not know, or a status word the contract does not define. The offline strip said "No active alerts" and the Production summary "everything looks normal" for those, because the alert grammar had no "not in" form | `ecco-geek-catalogue/1` gained two forms (`{attribute, not_in}`, strict; `{state_outside}`), and the generator emits `mode_not_shadow`, `applies_nothing_not_true`, `contract_mismatch` (critical) and `status_unrecognised` (warning), the values filled from the contract, never typed. `applies_nothing_not_true` lists false, "false" and "False" too, so the two `applies_nothing` alerts partition the values: no value raises both, only the boolean true raises neither. New fixture `contract-breach` (status OK, mode ASSISTED, watchdog on) | 17 scenario tests on the healthy fixture with the watchdog still on (both modes, role alert, summary not "looks normal"); grammar tests; `test_geek_mode_catalogue.py` checks the four alerts against the watchdog template's own text; mutants `AC6-not-in-*`, `AC6-state-outside-*`, `AC6-in-and-not-in-both-accepted` (7) |
| 5 | MINOR | The child-card guard allowed picture-glance and area cards (toggle by default), any `custom:` card (a button card taps to toggle) and a buttons footer: none carries an explicit `action` key | the guard is an **allowlist** of card types (also inside stacks, grids and conditionals, and for a header or footer), plus the read-only ECCO Intelligence card and any custom card the dashboard author names in the new `allow_custom_cards`; a heading badge on a writable entity must state a safe action; `counter`, `timer` and `group` count as writable domains | `core.test.mjs` (5 tests), `element.test.mjs` (1); mutants `AC16-allowlist-off` and 7 more (8) |
| 6 | MINOR | Redaction edge gaps: short values under compound key names (`encryption_key`, `wifi_key`, `pin`), a JSON credential pair, labelled coordinates, a secret split by a zero-width character or written with a look-alike Cyrillic or Greek letter, a bare internal host (`ws://homeassistant:8123`) | keys and values are matched on a folded copy (invisible characters removed, NFKC, look-alike letters turned into Latin; what is shown is never the folded copy); a key that ends in a key word after a qualifier, `pin` and `psk` are secret; the credential-pair pattern allows quotes; labelled and hemisphere coordinates (`52.1 N 0.12 W`) and one-word hosts are withheld; hostile fixtures for each, assembled from fragments | `secrets.mjs` (10 values, 9 keys) run through every surface by the existing hostile tests, plus 5 new tests; mutants `AC10-*` (10) |
| 7 | MINOR | Two reviewer mutants survived: the age read from `last_changed` (R40) and the row cap raised to a billion (R22) | tests with `last_changed` far older than `last_updated`; a 1000-character attribute cut at 300 with its marker | `core.test.mjs`; mutants `AC9-age-from-last-changed`, `AC12-row-value-uncapped` |
| 8 | MINOR | Every new `hass.states` object (Home Assistant sends one for any change in the house) rebuilt the whole snapshot in both modes with no coalescing | a rebuild happens only when something the view reads changed (state objects of the last snapshot's entities, or the entity count); built rows are reused per state object; a burst beyond eight relevant updates per 500 ms is coalesced into one rebuild at its end by the one timer slot (which also runs the 15 s age tick); a theme change is applied at once | element tests: 200 unrelated updates, no snapshot; 101 relevant updates in a burst, a bounded number of rebuilds, the last value and a critical alert shown after it, the next update immediate again; nothing pending survives disconnect; core test: an unchanged hass constructs no row, one changed entity one row; mutants `AC12-*` (6) and `AC14-theme-not-synced-on-set` |
| 9 | NIT | A timestamp a day in the future was LIVE, "just now"; `stale_after_s: 0` was accepted and meant "never stale"; only `simulated` and `synthetic` were read as simulated | more than five minutes ahead of the clock is UNVERIFIED with no age; `stale_after_s` must be above 0 or null; a provenance, data source or source kind starting with simulated, simulation, synthetic, fixture, mock, demo, sample, fake or dummy is SIMULATED (documented) | `core.test.mjs` (3 tests); mutants `AC9-*` (4) |
| 10 | NIT | A numeric state `-5` was exported to CSV as `'-5` | a plain number is exported exactly; anything else that starts like a formula is still neutralised | `core.test.mjs`; mutant `AC11-csv-numbers-guarded` |
| 11 | NIT | The Python privacy scanners had no bearer, credential-pair or webhook-path pattern: a generator that emitted one would have passed the scan (reviewer mutant PY06) | three scanners with negative controls, and the strict scan as a function proven against a value injected into a copy of the healthy fixture | `test_geek_mode_privacy.py`; with the three scanners removed the injected-value check fails |

### 13.2 What the owner needs to know

1. **The `hass-more-info` event is a write path for a writable domain.** The agreed interface allows it, and for a sensor, binary sensor or event
   it is read-only, but the dialog of an automation, a helper, a switch, a script, a button, a number, a select or an update has controls. Geek
   Mode now opens only the read-only domains. The guard for `always` child cards still allows a `more-info` action on any entity (the
   interface), so a card there that opens a writable entity's dialog would give the same extra path; nothing in the example does. Whether to refuse
   that too is an owner decision (section 8, item 11). Even a read-only domain's dialog has Home Assistant's own entity Settings tab for
   administrators: that is Home Assistant's permission model, not an ECCO control, and the shell cannot change it.
2. **The catalogue schema grew by two condition forms** (`{attribute, not_in}` and `{state_outside}`): an addition, no existing form changed. A
   card from before this round refuses an alert whose condition it does not know and therefore fails closed (no inventory, a visible error), so the card
   and the catalogue must be deployed together. Both are part of the same integration steps (section 8).
3. **The default custom-card list has one entry**, `custom:ecco-intelligence-card`, because it is the only ECCO card whose suite pins it read-only.
   The other ECCO cards were not reviewed here; a dashboard that wants one inside an `always` region names it in `allow_custom_cards` after the owner has
   checked it (section 8, item 12).
4. **Clock skew is now visible.** A browser whose clock is more than five minutes ahead of Home Assistant shows every row as Unverified (no age)
   rather than "just now"; a clock behind Home Assistant shows older ages. Both are honest, neither is guessed away.
5. **Two things were left as they are, on purpose.** `token abc123def` (a credential word and a value separated by a space only) is not
   withheld: that shape is too common in ordinary text to withhold by pattern, and a catalogue `exceptions` entry or a key rule is the right
   tool. A 34-letter lowercase run is not withheld either (no digit or capital, so it is not an encoded secret by shape).

### 13.3 Results of the runs

| Run | Result |
|---|---|
| `node --test test/*.test.mjs` (core 120, element 106, coverage 4, static 23, real-catalogue 157, mutation proof 137) | 547 of 547 pass; 135 of 135 mutants killed (86 before this round) |
| the new tests run against the card as reviewed (`ECCO_MODE_SHELL_PATH` pointing at a copy of it) | 47 of the new tests fail there, and so do 8 existing tests that now also run the new hostile shapes or pin the new alert count; every one passes with the fixes |
| `python -I -B -X utf8 test/test_example_dashboard.py` | 31 checks pass (new: every card type in the example's `always` list is on the shell's allowlist) |
| `tools/tests/test_geek_mode_{catalogue,coverage,ledger,fixtures,privacy,example}.py` | all pass (110, 110, 52, 102, 135 and 35 checks) |
| `tools/gen_geek_fixtures.py --check`, `tools/geek_mode_coverage.py --check` | both match a fresh regeneration |
| `tools/validate_repo.py` | PASSED, with no edit to any pinned file |
| `tools/run_offline_tests.py --root tools/tests`, `ecco_core/tests`, `health/tests` | 21 of 21, 6 of 6 and 2 of 2 |
| `tools/run_offline_tests.py --root` `intelligence/tests`, `home-assistant/tests`, `registry/tests` | 33 of 33; 17 of 18 on the first run (a new test of this round named the reserve helper's id, which `test_ecco_intelligence_prefs_package.py` allows only its package and itself to do: the id is assembled in the test now and that suite passes); 75 of 78 on the first run, and the lint `registry/tests/test_offline_suite_exit_codes.py` failed because the six Geek Mode suites took `check()` from a shared helper (it failed at the commit before this round too; they now carry the repository's own `check()` / `FAILURES` style and the lint passes). The two that remain, `test_rtc_policy.py` and `test_fallback_durable_host_compile.py`, need a C++ compiler this PC does not have (`ECCO_CXX`) and read nothing this change touches |
| the reviewer's probes P1 to P7, re-run against the fixed card | P1: Production after `setConfig`. P2: no Open button for the reserve helper, the alert automation or the pause helper, no event. P3: a day-ahead timestamp is Unverified with no age; `source_kind: fixture` is Simulated. P4: the compound keys, the JSON pair, the zero-width and homoglyph cases, the bare host and the labelled coordinates are withheld. P5: ASSISTED, `applies_nothing` 0 and "no", contract 2 each raise their critical line, WEIRD a warning. P6: picture-glance, area, a custom card and a heading badge on a writable entity are refused. P7: `-5` is exported exactly |

The integration steps of section 8 are unchanged by this round except for the two new decisions (items 11 and 12); no pinned or deployed file was edited.

### 13.4 Changes to existing tests (none weakens an assertion)

- `real-catalogue.test.mjs`: the pinned alert count 15 became 19 (four alerts were added by design); the helpers that state how each condition form can
  be triggered and read (`triggers`, `documentedConditionIds`) gained the two new forms; the expected-alerts table gained the new fixture.
- `element.test.mjs` and `real-catalogue.test.mjs`: the shared `mount` helper opts the test stub card in with `allow_custom_cards`, because custom cards
  in an `always` region now need a name; a new test proves the same stub is refused without it.
- `mutations.test.mjs`: the target text of `AC16-guard-off` follows the guard's new argument (the mutant still switches the guard off).
- `test_geek_mode_ledger.py`: the fixtures that exercise the OK advice keys now include `contract-breach` (a copy of the healthy fixture with one attribute changed).
- `secrets.mjs`: ten hostile values and nine hostile key names were appended (the indices of the existing ones did not move), so every existing hostile
  test now also runs the new shapes.

## 14. Review round 2 (15 Nov 2026): findings and fixes

The second independent review (mutants of the card and of the data side, and probes P8, P9 and P11) found one MAJOR and four smaller
findings, all in the guards around the proof rather than in the shell's behaviour. Each was reproduced first (the survivor run against the committed suites, or
a probe), then fixed; each fix has a test that fails without it, and a mutant that undoes it. No assertion was weakened or deleted (section 14.4). Still the same
rules: new files only for anything pinned or deployed, nothing live, nothing pushed.

### 14.1 The findings and what was done

| # | Severity | Finding | Fix | Proof |
|---|---|---|---|---|
| 1 | MAJOR | Reviewer mutant R2-16: a stylesheet rule that picks the Geek body out by position (`.shell:has(> .region:last-child:not([hidden])) .alerts{margin-left:-200vw}`) moved the alert strip off screen in Geek Mode only. The round-1 reader looked for a mode token and for display, visibility, opacity, size, clip and off-screen offsets of three digits: this rule has no mode token and uses a margin, so every suite passed | `static.test.mjs` reads the stylesheet in three layers. (1) The selectors that may NAME the strip or a part of it are an exact pinned list (11 selectors, all in use): a new one fails, however harmless its declarations. (2) No rule but `[hidden]` may use `:has()`, `:is()`, `:where()`, a positional pseudo-class, the hidden attribute (also inside `:not()`) or a sibling combinator. (3) A rule that can reach the strip (it names it, it applies to the shell, or what it applies to has no class to tell it apart: `*`, a tag, an attribute, a bare pseudo-class) may not carry a margin, inset, position offset, `translate` or `transform: translate` that is negative, huge (100 px, 8 rem, 50 % or any viewport or container unit from 50) or cannot be judged (`var()`, `calc()`, `min()` ...), a `display` or size taken from a variable, an animation (and every `@keyframes` rule is checked as reaching), or an `overflow` clip together with a height of a few pixels. Everywhere: a negative `z-index`, `scale: 0`, `zoom: 0`, `filter: opacity(0)` and the logical sizes (`block-size: 0`, `max-inline-size: 0`) join the hiding list | `static.test.mjs`: 4 new tests (the pinned list is exactly what the stylesheet uses; which rules reach the strip; R2-16 and 59 other hostile rules, each also appended to the real stylesheet; the length reader) and 19 harmless rules, several the real stylesheet's own; mutants `AC6-css-*` (8 new, R2-16 itself first) |
| 2 | MINOR | Reviewer mutant R2-36: removing the `watch.add` for an alert's entity left every suite passing, because on the Intelligence catalogue every alert entity is also a source. On another tab an alert on an entity that is not a source would reach the strip only at the next update more than one second later or at the 15 s tick (probe P8). Reviewer mutant PY2-06: removing the coverage check that every alert names a catalogued source also passed every Python suite and `--check` | an element test with a catalogue whose alert names an entity outside the sources (the strip updates on the next `hass`, in both modes, half a moment after the last rebuild; an unrelated entity still costs nothing) and a core test of `snapshot.watch`; a coverage negative control (an alert on an uncatalogued entity must produce the problem line, and `--check` must fail) | mutant `AC12-alert-entity-not-watched`; `test_geek_mode_coverage.py` fails with the check removed (shown on a temporary edit of the tool, restored) |
| 3 | MINOR | Reviewer mutant R2-41: when the catalogue is invalid, an `effective` catalogue that kept the valid sources and discovery passed every suite. Probe P9 (one malformed source) then put 16 rows in `el.snapshot` and the Production summary said that ten data points are stale, unavailable, simulated or unverified and that Geek Mode lists them, while Geek Mode shows only the error panel | an element test: with one malformed source the snapshot holds no row (not the valid sources, not a discovered one, not after a later update), the summary has no problem note, and the strip still shows the valid alerts and the catalogue error | mutants `AC16-invalid-catalogue-keeps-sources` and `-keeps-discovery` |
| 4 | MINOR | Probe P11: a Home Assistant webhook URL under an innocent key and a login name under `mqtt_user` were shown verbatim; the Python strict scanners had a webhook pattern since round 1 and the card had none, so the two sides disagreed | a value rule for a webhook path, the same pattern as the Python scanner's (a privacy test now compares the two texts), and a key whose last word is user, users, usr, login or logins after a qualifier is private (`mqtt_user`, `db_login`, `serviceUser`; a bare `user` stays visible, as a bare `key` does); three webhook values and five login keys are in the hostile fixtures, so every existing hostile test runs them too | 3 new core tests (the two rules with the ordinary cases that stay visible, and every path); the existing hostile tests fail on the card as reviewed; mutants `AC10-no-webhook-rule`, `-webhook-services-form-dropped`, `-login-key-rule-dropped`, `-login-key-needs-no-qualifier` |
| 5 | NIT | A row built for a state object was reused for up to one second, so it could show LIVE for less than a second after its age passed `stale_after_s` (and Unverified for less than a second after a skewed timestamp stopped being skewed); during a burst of more than eight updates in 500 ms the child cards get every `hass` at once while the shell snapshot is coalesced, so the two can differ for up to about 500 ms | a reused row is re-classified (one `classifyRow`, a few date parses) and is kept only when its status and flags are what a fresh classification gives; the age text may still lag by less than a second. The coalescing bound is documented here, next to AC7 (section 5) and in the README | 3 core tests (a row built 0.4 s before its limit is STALE on time and only that row is rebuilt; 55 age and offset cases around the stale limit and the skew limit equal a fresh classification; a reused row is not reused for ever); mutants `AC9-row-reuse-skips-reclassification` and the round-1 `AC12-row-reuse-ignores-clock` (re-aimed) |

What the mutation proof added to the suite itself: after the first full run two of the new mutants survived. The services-form webhook value I had picked
(a Slack-like path with capitals and digits) was withheld by the long-encoded-value rule anyway, so removing the webhook rule's second form changed nothing: the
fixture now has a form no blob rule can reach. And the round-1 mutant `AC12-row-reuse-ignores-clock` stopped being killed by the element tick test (the re-classification now keeps the
status right on its own) and was found to have been killed in `core.test.mjs` only by accident (a second catalogue object in the test rebuilt every row): a test that keeps the
catalogue and the state objects and reads them five seconds later now pins the window.

### 14.2 What the owner needs to know

1. **The stylesheet reader is deliberately strict.** A new rule that names the strip, or that uses `:has()`, a positional pseudo-class, a sibling combinator or the
   hidden attribute, fails `static.test.mjs` even if it is harmless; the person adding it updates the pinned list in the test, which is the point (a decision, in a
   diff a reviewer reads). The shell's own rules need none of these.
2. **A negative margin on a class the strip does not carry is fine** (the real `.mode-note` has one); the reach test is on what the rule applies to, not on the
   property alone. A rule on a bare tag, `*` or an attribute counts as reaching the strip.
3. **The coalescing bound.** During a burst of more than eight relevant updates in 500 ms the child cards (the existing Intelligence card among them) are handed every
   `hass` at once, while the shell's strip, summary and Geek rows catch up in one rebuild at the end of the burst: for up to about 500 ms the two can differ. A critical
   alert is never delayed by more than that, and the 15 s tick re-derives everything. This is bounded and small; it is written next to AC7 so that nobody reads
   "same data" as "same instant".
4. **Two more words are private by key** (`user` and `login` after a qualifier): `last_user` or `active_users` would be withheld too. Over-withholding is the safe
   side; a catalogue that needs such a key shown can say so in `exceptions` once the owner decides.
5. Nothing else changed for the owner: the integration steps of section 8 are unchanged, no pinned or deployed file was edited.

### 14.3 Results of the runs

| Run | Result |
|---|---|
| `node --test test/*.test.mjs` (core 127, element 108, coverage 4, static 27, real-catalogue 157, mutation proof 153) | 576 of 576 pass; 151 of 151 mutants killed (135 before this round) |
| the new tests run against the card as reviewed (`ECCO_MODE_SHELL_PATH` pointing at a copy of it) | 12 fail there: the five new tests of the reuse, webhook and login rules and the seven existing hostile-value tests that now also run the new shapes; the stylesheet, watch and fail-closed tests are shown by the reviewer's own mutants, each reproduced as a survivor against the round-1 suites and killed now |
| `python -I -B -X utf8 test/test_example_dashboard.py` | 31 checks pass |
| `tools/tests/test_geek_mode_{catalogue,coverage,ledger,fixtures,privacy,example}.py` | all pass (110, 112, 52, 102, 137 and 35 checks) |
| `tools/gen_geek_fixtures.py --check`, `tools/geek_mode_coverage.py --check` | both match a fresh regeneration |
| `tools/validate_repo.py` | PASSED, with no edit to any pinned file |
| `tools/run_offline_tests.py --root` `tools/tests`, `ecco_core/tests`, `health/tests`, `intelligence/tests` | 21 of 21, 6 of 6, 2 of 2 and 33 of 33 |
| `tools/run_offline_tests.py --root` `home-assistant/tests` and `registry/tests` | 18 of 18 and 76 of 78; the two that fail, `test_rtc_policy.py` and `test_fallback_durable_host_compile.py`, need a C++ compiler this PC does not have (`ECCO_CXX`), failed the same way in round 1 and read nothing this change touches |

### 14.4 Changes to existing tests (none weakens an assertion)

- `static.test.mjs`: the stylesheet reader's declaration tuples gained a third element (the value with its spaces kept), `hidingDeclaration` and `cssViolations` were
  rewritten around the three layers above; every round-1 negative control still passes (each is still reported) and the round-1 assertions are unchanged.
- `core.test.mjs`: the round-1 test of the hostile edge values takes `SECRET_VALUES.slice(21, 32)` instead of `slice(21)`, so it still checks its eleven values (the three
  webhook values were appended to the same list); a new test runs the three on every path.
- `mutations.test.mjs`: the target text of `AC12-row-reuse-ignores-clock` follows the re-aimed guard (the mutant still removes the one-second window).
- `secrets.mjs`: three hostile values and five hostile key names were appended (the indices of the existing ones did not move).

## 15. Review round 3 (15 Nov 2026): findings and fixes

The third independent review found one MAJOR, which it called structural, and two MINOR findings. The MAJOR: rounds 1 and 2 each answered a reviewer mutant by adding
it to a list of ways to hide the alert strip, and each round the reviewer found one the list did not hold. This round does not extend the list. Each finding was
reproduced first (the reviewer's mutants run against the committed suites, and the probe), then fixed; each fix has a test that fails without it, and a mutant that
undoes it. No assertion was weakened or deleted (section 15.7). The same rules held: nothing pinned, sealed or deployed was edited, nothing is live, nothing was pushed.

### 15.1 The findings and what was done

| # | Severity | Finding | Fix | Proof |
|---|---|---|---|---|
| 1 | MAJOR | Reviewer mutants R3-C1 to R3-C7: `.shell[DATA-MODE=geek]>[role=region]{transform:rotateX(90deg)}` (C1), `...>[aria-live]{font-size:.01px}` (C2), `div[aria-live]{color:rgba(0,0,0,0)}` (C3), `[aria-live]{transform:scale(.001)}` (C4), `...>[aria-live]{order:99}` (C5), the R2-16 literal (C6) and `[aria-live]{filter:blur(40px)}` (C7). C1 to C5 and C7 survived every node suite (C6 was already killed): the mode token was case-sensitive although HTML attribute names in a selector are not, `[role=region]` and `[aria-live]` were not counted as naming the strip, and rotateX, a tiny font, scale(.001), a transparent colour, a blur and `order` were not in the list of hiding declarations. Headless Chrome measured the Geek strip at height 0.00 and the Production strip at 18.00 | Four nets, none of which asks "is this a known way to hide it" (section 15.2): the PIN of every rule, selector and declaration; the ALLOWLIST of properties a rule that can reach the strip may set; a strict READER that refuses what it cannot judge; and the opt-in headless Chrome check that measures what is drawn. The mode and strip tokens are case-insensitive and the strip token names `role`, `aria-live` and `aria-label` | `static.test.mjs` 11 new tests (38 in all); `strip-check.test.mjs` 10 tests; R3-C1 to R3-C7 and 136 declarations on 12 selectors (1632 combinations) are negative controls for both the semantic net and the pin, each also appended to the real stylesheet; 23 new mutants (21 `AC6-css-r3-*`, 2 `AC6-strip-*`); `check-strip.mjs --selftest` catches 25 of 25 broken copies |
| 2 | MINOR | Reviewer mutant R3-20: `down \|\|` read as `!input.present \|\|` in the `state_not_in` branch survived every suite, because the one catalogue alert that uses `state_not_in` lists neither `unknown` nor `unavailable`. The Intelligence catalogue has none, so the mutant is equivalent on this tab and matters when the shell is reused | a core test pins the fail-safe reading and the reading is documented: an entity that is down (missing, unavailable or unknown) FIRES a `state_not_in` alert even when the list itself names `unknown` or `unavailable`; an entity that is up reads the list as written | `core.test.mjs` `AC6 [r3] state_not_in is fail-safe`; mutant `AC6-not-in-down-honours-list` is R3-20 |
| 3 | MINOR | Probe `probe.mjs`: values passed through `redactValue` under an innocent key were shown: a key named `wifi_pass` or `pw`, a MAC address with no separators or in the dotted form, a coordinate pair with three decimals, the text of a Wi-Fi QR code and a JSON-like `{"pass": ...}` string. None occurs in the Intelligence data | key rules: `pass` as the last word after a qualifier (`wifi_pass`, `mqttPass`; a bare `pass` is shown, it is also a test result), `pw` in any position, the compact `wifipass` and `wifipw`. Value rules: the dotted MAC (needs a letter, so a version number is not one), twelve hex digits with no separator (needs a letter; a revision key may hold a short git revision), a coordinate pair from three decimals, the text of a Wi-Fi QR code, a quoted `pass` or `pw` pair and `pass=value`. The hostile fixtures (12 values, 8 keys) and the Python STRICT scanners follow, and a privacy test compares the card's two new rule texts with the scanners' | `core.test.mjs` 4 new tests; `secrets.mjs` `SECRET_VALUES_R3` and `SECRET_KEYS_R3` run in every end-to-end hostile test; 13 new mutants `AC10-*`; `test_geek_mode_privacy.py` 9 new checks (146 in all), shown to fail with each new scanner broken |

How the failures were shown. Against the committed round-2 suites the reviewer's mutants were run first: C1 to C5, C7 and R3-20 pass 423 of 423 (survive), C6 fails 3
(killed). With this round's suites the same seven stylesheet mutants fail 5 to 7 tests each, including tests that already existed (the case-insensitive tokens make the
round-1 and round-2 tests see them), the new pin and allowlist tests, and the headless Chrome check (372, 156, 240, 480, 204, 228 and 48 failing checks). The new
redaction tests fail on the card as reviewed (copy of it in scratch, `ECCO_MODE_SHELL_PATH`): 9 tests, four of them new and five existing hostile-value tests that now also run the new shapes.

### 15.2 The four nets for the alert strip, and what each cannot see

1. **The pin** (`test/fixtures/style.pin.json`, read by `static.test.mjs`). `test/css-guard.mjs` parses the stylesheet into a canonical list of 135 rules: the at-rule
   context, the selectors and each declaration with its value. The pin holds the list a person approved. Any new selector, any new or changed declaration or value, a
   removed or re-conditioned rule and a changed order of rules fails the test until the file is regenerated (`node test/style-pin.mjs > test/fixtures/style.pin.json`)
   and its diff reviewed with the stylesheet change. White space, a trailing semicolon and the case of a property name are free. Nothing in the repository writes
   the pin: regenerating it IS the decision. This is the mandatory net: it does not need to know what a rule does.
2. **The allowlist** (`STRIP_ALLOWLIST` in `css-guard.mjs`). A rule can reach the strip when it names it (the token now includes `role`, `aria-live` and `aria-label`),
   when it applies to what contains it (`.shell`, `:host`) or to something with no class (a tag, `*`, an attribute, a pseudo-class), and when every class it asks for
   is one the strip, its parent and its lines can carry; a rule on `.row` or `.healthbar>span` cannot reach it. In a rule that can reach the strip, every declaration
   must be on the list with a bounded value: 37 properties (display grid, flex or block; gap, padding and margin up to 32, 48 and 24 px, never negative; colours with
   a minimum opacity; border, outline, font-size 12 px or more, a font shorthand of 12 px or more; the icon's size 16 to 48 px; and so on). A property that is not on the
   list is refused however harmless it looks: transform, rotate, scale, translate, filter, opacity, clip-path, mask, visibility, content-visibility, contain, position,
   inset, z-index, order, line-height, height, max-height, overflow, text-indent, pointer-events and everything else. `!important` is refused except in the one
   reduced-motion rule and the `[hidden]` rule. Custom properties and `var()` are accepted in such a rule only for the 15 pinned theme names, in a colour position,
   with a visible colour as the value. The real stylesheet's 30 reaching rules (and its 2 keyframe rules, which may animate only box-shadow) all pass.
3. **The strict reader** (`parseSheet`). It refuses what it cannot judge instead of guessing: a backslash (a CSS escape), a comment (one between a property and its colon
   changes a rule's meaning), an HTML comment token, a control character, an `@import`, `@charset` or any other statement at-rule, an at-rule or condition that is not on the
   pinned list of six (`@media`, `@container` and `@supports` blocks nobody pinned), an at-rule inside an at-rule, a nested rule or `&` (CSS nesting), a declaration with no colon or an odd
   property name, and unbalanced braces. The round-2 reader treated an `@import` followed by a rule as one at-rule and read none of the rule.
4. **The headless Chrome check** (`preview/check-strip.mjs`, opt-in, section 15.5). It never reads the stylesheet. It measures what the browser computed and drew for the
   strip in 48 states and requires, among other things, a real box inside the viewport and the card, opacity 1, no transform, filter, clip, mask or containment on it or
   any ancestor, nothing covering it, text of 12 px or more at 4.5 : 1, and the same box in both modes.

What each cannot see, honestly:

- The pin is a person's decision, not a proof: a person can regenerate it over a harmful rule. What it guarantees is that no change to the stylesheet passes unseen.
- The allowlist reads rules, not the cascade or the document. A rule on a neighbour of the strip can overlap it (for example `.top` positioned, with a negative bottom margin
  and a higher z-index: the self-test's "covered by a positioned block"); the strict reading does not judge rules on classes the strip cannot carry. The pin and the browser
  check catch it. Two colours that are each allowed (the theme variables for text and surface set to the same value) are unreadable together: the pin and the browser check
  catch that, the allowlist cannot.
- The browser check runs two window sizes (520 and 1100 px wide; Chrome clamps a headless window to about 500 px) and two card widths (390 and 1000 px), at load and after
  the mode switch. It does not resize, scroll, animate, use a different font, or follow a data change after the first render. Contrast is computed from the
  computed colours and the background colours of the line's ancestors; a gradient or an image behind text is not measured (the shell has none behind the strip). It
  is run by a person: it is not part of `node --test`, and without Chrome or Edge it prints SKIPPED.

### 15.3 Redaction: what the new rules catch, and what is still shown

New (section 15.1, finding 3): `wifi_pass`, `mqttPass`, `pw` and the compact `wifipass` and `wifipw` as key names; the dotted three-groups-of-four MAC; twelve hex digits with no
separator and at least one letter (not under a revision key); a coordinate pair of two numbers with three or more decimals; text that starts like a Wi-Fi QR code; a
quoted `pass` or `pw` key with a value and `pass=value` or `pw=value`. **Over-withholding, deliberately:** any key with `pw` in it; a key that ends in `_pass`
(a self-test result named `self_test_pass` would be withheld); a pair of two ratios with three decimals written as one string (`0.125, 0.250`). Plain prose such as `pass: true`, a
version number such as `2026.1114.0900`, twelve plain digits and a pair with one coarse number are shown (tests).

Still shown, found by the probe and not in the finding: a position written in degrees, minutes and seconds (`51 30 26 N 0 7 39 W`); a phone number; a post code; an Open Location
Code or a geohash; a chat-bot token inside a URL path (`.../bot<digits>:<token>/sendMessage`); a webhook id shorter than eight characters; a notification topic name used as a URL path;
a JWT-like text with three very short parts; a short base64 password; a private address written inside a longer word; and compact key names that join a secret word to
another word without a separator (`wifipassword`, `adminpassword`). None occurs in the Intelligence data (the strict scanners find none in any committed fixture or in the catalogue).
The redactor is a heuristic net with an exceptions list, not a proof: for another tab, run the strict scanners over its fixtures and extend the catalogue's `extra_key_patterns` for
the names that tab's integration uses.

### 15.4 What the owner needs to know

1. **Changing the stylesheet now needs the pin regenerated in the same commit.** That is the intended friction: a person reads the new rule, runs `node test/style-pin.mjs`, and
   the diff of `style.pin.json` goes to the reviewer. A rule that can reach the strip must also fit the allowlist. The shell's own rules need nothing else.
2. **A mode or strip selector in any case is now a mode or strip selector** (`[DATA-MODE=geek]`, `[Role=region]`, `.ALERTS`). The old tests therefore also fail on the reviewer's
   mutants; they were not changed.
3. **`state_not_in` is fail-safe and says so** (finding 2). A catalogue that wants "alert unless the state is one of these, and say nothing when the source is down" cannot be written
   with it; use `state_in`, or the `unavailable` form for the down case.
4. **The browser check is run by a person** (`node preview\check-strip.mjs`, and `--selftest`). It found no defect in the shell itself: the real card passes all 2856 checks.
5. Nothing else changed for the owner: the integration steps of section 8 are unchanged, no pinned or deployed file was edited.

### 15.5 The browser check, run

On this PC (Google Chrome 157, headless, window 520 x 1500 with a 390 px card, and window 1100 x 1500 with 390 and 1000 px cards):

| Run | Result |
|---|---|
| `node preview/check-strip.mjs` | PASS: 48 states measured (scenario with alerts of every severity and a healthy one, x light and dark, x with and without Home Assistant's theme variables, x Production and Geek, x the widths), 24 Production / Geek pairs; 2856 of 2856 checks hold. About two seconds |
| `node preview/check-strip.mjs --selftest` | SELFTEST PASS: the unbroken card passes, and each of 25 broken copies fails (R3-C1 to R3-C7; display none, visibility, opacity .02, height 0, off screen, clip-path, mask, line-height 0, text colour equal to the background, equal theme colours, faint text, a covering block, a sideways shift, content-visibility, size containment, an inline style on the strip, the strip hidden by the code in Geek Mode, only the first alert in Geek Mode). 36 to 648 checks fail on each (108 for the equal theme colours). About 40 seconds |
| the reviewer's seven mutants, one by one (`--card`) | all seven fail: 372, 156, 240, 480, 204, 228 and 48 of 2856 checks |
| no browser | prints SKIPPED in a banner on stdout and stderr and exits 0 (3 with `--require`); `findBrowser` is unit-tested with a fake file system |

### 15.6 Results of the runs

| Run | Result |
|---|---|
| `node --test test/*.test.mjs` (core 132, element 108, coverage 4, static 38, real-catalogue 157, strip-check 10, mutation proof 190) | 639 of 639 pass; 188 of 188 mutants killed (151 before this round: 37 new) |
| the reviewer's seven stylesheet mutants against the round-two suites, then against these | before: C1 to C5 and C7 pass 423 of 423 (survive), C6 fails 3; after: each fails 5 to 7 tests |
| the new redaction tests against the card as reviewed (`ECCO_MODE_SHELL_PATH` pointing at a copy of it) | 9 fail there (four new tests and five existing hostile-value tests that now also run the new shapes); the `state_not_in` test fails on mutant R3-20 and passes on the card |
| `python -I -B -X utf8 test/test_example_dashboard.py` | all example-dashboard checks pass |
| `tools/tests/test_geek_mode_{catalogue,coverage,ledger,fixtures,privacy,example}.py` | all pass (110, 112, 52, 102, 146 and 35 checks; the privacy suite gained 9) |
| `tools/gen_geek_fixtures.py --check`, `tools/geek_mode_coverage.py --check` | both match a fresh regeneration |
| `tools/validate_repo.py` | PASSED, with no edit to any pinned file |
| `tools/run_offline_tests.py --root` `tools/tests`, `ecco_core/tests`, `health/tests`, `intelligence/tests` | 21 of 21, 6 of 6, 2 of 2 and 33 of 33 |
| `tools/run_offline_tests.py --root` `home-assistant/tests` | 18 of 18 |
| `tools/run_offline_tests.py --root registry/tests` | not run to completion in this round: it was still working through the registry suites (more than thirty of 78 done, none failed) when this record was written. It reads nothing this change touches (rounds 1 and 2 ran it: 76 of 78, the two that need a C++ compiler this PC does not have fail as before) |
| `node preview/check-strip.mjs`, `--selftest` | section 15.5 |

### 15.7 Changes to existing tests (none weakens an assertion)

- `static.test.mjs`: the two local constants `ALERT_TOKEN` and `MODE_TOKEN` were replaced by imports of the same names from `css-guard.mjs`; they are the old patterns made
  case-insensitive, with the strip token also naming `role=`, `aria-live`, `aria-label`, `aria-atomic` and `aria-relevant`. Every round-1 and round-2 assertion is unchanged and passes.
  `hidingDeclaration` was NOT extended: the point of the round is that it is not the net. Eleven tests were appended.
- `core.test.mjs`: the import line also takes `SECRET_VALUES_R3` and `SECRET_KEYS_R3`; five tests were appended. The round-two tests that address `SECRET_VALUES.slice(32)` and
  `SECRET_KEYS.slice(-5)` read the same values as before, because the new hostile values are in their own lists.
- `secrets.mjs`: two exports were added; `hostileAttributes()` and `forbiddenStrings()` carry them as well, so every existing end-to-end hostile test now also runs them.
- `mutations.test.mjs`: 36 mutants were appended (their count is in 15.6); nothing was removed or changed.
- `test_geek_mode_privacy.py`: five scanners and nine checks were added (the old scanners and checks are unchanged).

## 16. Review round 4 (15 Nov 2026): findings and fixes

The fourth review found two MAJOR findings and two NIT findings. Round 3's direction (pin the stylesheet, allowlist what can reach the strip, a strict reader, a behavioural browser net,
`state_not_in`, the redaction gaps) is complete and unchanged (section 15); this round does not redo it. Each finding was reproduced first (the reviewer's mutants run against the committed
suites), then fixed; each fix has a test that fails without it and mutants that undo it. No assertion was weakened or deleted (section 16.7). The same rules held: nothing pinned, sealed or
deployed was edited, nothing is live, nothing was pushed.

### 16.1 The findings and what was done

| # | Severity | Finding | Fix | Proof |
|---|---|---|---|---|
| 1 | MAJOR | Reviewer mutants J2 (`ui.strip.setAttribute('aria-hidden', mode === 'geek' ? 'true' : 'false')`) and J5 (`aria-live` set to `off` in Geek Mode) survived all five node suites AND the round-3 headless Chrome check (2856 of 2856). A screen-reader user in Geek Mode would get no safety alert while Production still announced them. A comment in `static.test.mjs` said aria-hidden writes were pinned; no assertion checked one | The CSS nets cannot see an attribute, so the same structural rule is applied to attributes (section 16.2): every attribute write of the card is at a pinned site; the aria / role / tabindex keys of every built element are counted; no other door to an accessibility property exists; the element tests compare the strip, everything around it and every alert line in both modes and require region / polite / a label / role alert or status / no aria-hidden, inert or hidden; the browser check reads the same attributes and compares them in both modes | `test/aria-guard.mjs` and 3 tests in `static.test.mjs` (a pin of 18 sites; 39 planted breaks, each also appended at the end of the module); 2 tests in `element.test.mjs` (9 scenarios x 6 steps; 23 planted attribute changes); 3 new checks per state, 1 per alert line and 3 per pair in the browser check (3192 checks, from 2856), shown by 26 offline measurement controls; 21 new mutants (J2, J5 and 19 variants); the self-test has 6 more broken copies (31 of 31 caught) |
| 2 | MAJOR | Reviewer mutants P3 (an `input_number` in the main package) and P5 (a template `sensor` named `ECCO Intel zz probe`): `tools/geek_mode_coverage.py --check` still printed "match a fresh regeneration" and exited 0. `_package_entities` read only `input_boolean`, template `binary_sensor` and `automation` (and `input_number` of the prefs package) and skipped anything else, so a new package entity was neither COVERED nor an EXCEPTION in the ledger, which breaks AC15 | `_package_entities` fails closed (section 16.3): every top-level key of the three Intelligence package files and every kind of entity in a template block is either modelled or refused with a `UniverseError` that names it; a fourth `ecco_intel*` package file, a missing one, a malformed one and an entity id defined twice are refused too | `test_geek_mode_coverage.py` 56 new checks (block [6]: 52 checks, 50 of them package cases; and P3 and P5 as mutations of a scratch tree: 4 checks); `test_geek_mode_ledger.py` 8 new checks (block [6]: P3 and P5 end to end through `--check`, through the writer, and restored) |
| 3 | NIT | Probe: a MAC address written with spaces (`AA BB CC DD EE FF`) was shown, and so were prose such as `mqtt pass hunter22`, `p@ss: hunter22`, `0x1A2B3C4D5E6F` and a bare key named `pass`. The bare `pass` is a documented choice; none of these occurs in the Intelligence data | A value rule for six bytes separated by single spaces with at least one letter (`MAC address (spaced)`), the same pattern in the Python strict scanners (the privacy suite compares the two texts); the bare `pass` choice is written into the README and section 16.4; the other shapes are listed there as still shown | `core.test.mjs` 3 tests; `secrets.mjs` `SECRET_VALUES_R4` (3 values) in every end-to-end hostile test; 4 new mutants; `test_geek_mode_privacy.py` 3 new checks |
| 4 | NIT | Child cards are mounted inside the shell's shadow root. A child card that has no shadow root of its own could put a `<style>` element into its light DOM, and that stylesheet would apply to the strip; neither the pin nor `validateChildCards` sees it. Found by reading the code | Documented, not changed (section 16.4 and the README): the cards used today render into their own shadow root; a custom card in `always` must already be named by the owner; the production list is not filtered. A nested shadow root per region (or the browser check with that card mounted) is a decision for the second tab | none (documentation only) |

How the failures were shown. J2 and J5 were built from the committed card and run against the committed round-3 suites (the five node suites and the strip-check suite, 449 tests):
both pass 449 of 449; the round-3 browser check reports PASS 2856 of 2856 on each. Against this round's suites J2 fails 4 and J5 fails 3 of the new `AC6 [r4]` tests (the element
comparison, the source pin and one more of the source tests among them), and the new browser check fails 96 and 72 of 3192 checks. P3 and P5 were applied to a scratch copy of the
packages: `--check` exited 0 and said the files match; now it exits 1 with a finding that names the key, and the writer refuses as well (the new Python tests fail on the round-3 tool: 4 checks in the
ledger suite, 4 in the coverage suite before it stops on the missing constants).

### 16.2 The accessibility net, and what it cannot see

Three nets, none of which asks whether a break is one somebody has already thought of:

1. **The source pin** (`test/aria-guard.mjs`, used by `static.test.mjs`). Every `setAttribute`, `toggleAttribute` and `removeAttribute` call of the card must be one of 18 pinned sites, each
   written as method, attribute and receiver (`setAttribute('aria-hidden') on svg`, `setAttribute('aria-checked') on ui.opts[m]`, `setAttribute('aria-pressed') on ui.problems` are the only ARIA writes after a
   build: never the strip, the shell or an alert). The attribute name must be a single-quoted literal (or `k`, in the two builders that take it from the literal they are given), so a
   template literal, a concatenation, a variable and an upper-case spelling are each reported. The `role`, `aria-*`, `tabindex`, `hidden`, `inert`, `style`, `slot`, `part`, `popover` and `contenteditable`
   keys of every object literal are counted (for example `aria-live` in exactly two: the strip and the Geek status line). No other door is used: ARIA reflection properties (`el.ariaHidden`,
   `el.role`), attribute-node and named-item APIs, `classList`, `className`, `inert`, `Object.assign`, an alias, `call`, `apply` or `bind` of a method, a method reached by bracket. Formatting
   is free; a new write, a changed receiver or name, a second write at a pinned site or a removed one is reported until a person edits the pin in the same commit. The strip's own literal and its alert nodes
   stay pinned by the round-3 test.
2. **The element comparison** (`element.test.mjs`). In nine scenarios (a healthy view, the three severities together, each of the seven alerts), after the first render, in Geek Mode, after an update and a tick
   with a theme change, back in Production, again in Geek and again in Production, the strip's complete attribute map, the accessibility attributes of every ancestor up to the host, of the host itself and
   of every node inside the strip, and the role of every alert line are identical, and they satisfy the rule: role `region`, `aria-live` polite, a label, no `aria-hidden` (except the decorative icons), `inert`,
   `hidden` or `style`, role `alert` for a critical alert and `status` for the others, none on the quiet line. A second test plants 23 changes on a live element (aria-hidden true and false, aria-live off, removed and
   assertive, role presentation or removed, an empty or missing label, inert, hidden and style on the strip, aria-hidden, inert and a role on the shell and the host, hidden or aria-hidden on an alert line, a critical
   alert that is only a status, aria-live inside the strip) and requires each to be reported, and a changed label that is still a label to differ between the modes.
3. **The browser check** (`preview/check-strip.mjs`). It now also reads, from the real page, the `role`, `aria-hidden`, `aria-live`, `aria-label`, `aria-atomic`, `aria-relevant`, `aria-busy`, `inert` and `hidden`
   attributes of the strip, each of its ancestors (through the shadow root to the host and the page) and each alert line, and judges: none of `aria-hidden`, `inert`, `hidden` (of any value) on the strip or an
   ancestor; role `region`, `aria-live` polite and a label of at least five characters; no `aria-busy` or `aria-relevant`; the right role on each line; and the same attributes on all of them in both modes. The
   self-test gained six broken copies (J2, J5, aria-hidden on the shell, inert on the host, role presentation on the strip in Geek Mode, every alert line given role presentation).

What they cannot see, honestly:

- A static read of source cannot exclude every dynamic way to write an attribute (a method name computed at run time). The card already refuses `eval`, `Function`, `Reflect`, `Proxy`, `globalThis` and `document`, and
  the guard refuses the alias and bracket forms of the three methods; the two behavioural nets look at the result instead of the source, and between them a dynamic write is caught as soon as it happens on the strip,
  its ancestors, the host or a line.
- The DOM stand-in does not model ARIA reflection properties (`ui.strip.ariaHidden = 'true'` sets a JavaScript property and no attribute there): only the source pin and, in a real browser, the browser check (a real
  element reflects the property to the attribute) see that: the `ariaHidden` mutant fails 96 of 3192 browser checks. The mutation proof includes three such mutants, killed by the pin.
- None of the nets runs a screen reader or reads the browser's accessibility tree (it is not reachable from a headless page dump). The attributes are the evidence; a role Chrome computes differently from the attribute
  is not measured.
- A person can edit the pin over a harmful write. What the pin guarantees is that no new write passes unseen.

### 16.3 The package files fail closed

`tools/geek_mode_coverage.py` reads three package files of the Intelligence tab and now models exactly what they hold, constant by constant: `PACKAGE_MAIN_KEYS` (`input_boolean`, `template`, `automation` in
`ecco_intelligence.yaml`), `PACKAGE_PREFS_KEYS` (`input_number` in `ecco_intelligence_prefs.yaml`), `PACKAGE_DASHBOARD_KEYS` (`lovelace` in `ecco_intelligence_dashboard.yaml`, a registration that defines no entity: the
tool now holds it to that) and `TEMPLATE_BLOCK_KEYS` (`binary_sensor`). It raises a `UniverseError`, and so exits 1 for `--check` and for the writer, for:

- any other top-level key in a package file (an `input_text`, `input_select`, `counter`, `timer`, `script`, `sensor`, `group`, `homeassistant`, `mqtt`, `lovelace` in the wrong file and so on: 22 kinds are tested);
- any other key in a template block: a `sensor`, `number`, `select`, `button`, `image`, `weather`, `switch` or `light` block, or a trigger-based block (its `trigger` key is not modelled either);
- a fourth file whose name starts with `ecco_intel` in `home-assistant/packages` (any extension), or one of the three missing;
- a package that is not a mapping, a `template` that is not a list of mappings, an `automation` that is not a list, an automation or binary sensor with no usable alias or name, an `input_boolean` or
  `input_number` that is not a mapping of helpers, and an entity id that two definitions produce (two names that slug alike).

A kind the tool models (another alert automation with an `ecco_intel_` id, for example) passes the walk and is then caught by the coverage check as an uncatalogued source, as before. To add a new kind of
entity to a package file, model it in `_package_entities`, give it catalogue texts (or an exception with a reason from the fixed list), and the ledger is regenerated. Other package files
(`ecco_pro.yaml` and the rest) are not modelled; a data point defined in one of those is outside this ledger and would have to be discovered at run time (the card discovers `ecco_intel_` entities without a hand-designed card).
(Review round 5 changed what "not read" meant: every other YAML file under `home-assistant/` is now read, to refuse an `ecco_intel_` data point defined or named in it, so one cannot appear there unaccounted for: section 17.3.)

### 16.4 What is still shown, and the child cards' style scope

Redaction (finding 3). New: six bytes written with single spaces, at least one letter among them, anywhere in a string (`aa bb cc dd ee ff`, also inside a sentence), under any key except that a revision
key does not excuse it (a revision has no spaces). Over-withholding: any prose that happens to hold six two-digit hex bytes with a letter (`be ad ca fe 01 02`). **A bare key named `pass` is shown on purpose**
(`self_test: pass`, `pass: ok`): it is also a test result; a password under `wifi_pass`, `mqttPass`, `pw` and the other qualified names is withheld, and so is a quoted `"pass": "..."` pair inside a string.
Still shown, added to the list in 15.3: prose that names a password in words (`mqtt pass hunter22`), `p@ss: hunter22`, a MAC address written as a `0x` hex literal, and an all-digit MAC address written with spaces
(`00 11 22 33 44 55`), which cannot be told from six numbers. None occurs in the Intelligence data (the privacy suite's strict scanners, which now include the spaced form, find none in any committed fixture or in the catalogue).

Child cards (finding 4). The shell mounts child cards inside its own shadow root, in the `always` and `production` regions. A child that renders into its own shadow root (the ECCO Intelligence card, the pause
tile and Home Assistant's built-in cards do) cannot style the strip. A child with no shadow root of its own could add a `<style>` element to its light DOM, which belongs to the shell's tree scope and would apply to
the strip. The pin reads the shell's `STYLE`, `validateChildCards` reads a child's configuration, and the browser check mounts no child, so none of them sees it. Two controls exist today: a custom card in `always`
must be named in `allow_custom_cards` by the owner, and the `production` list is not filtered (controls live there). Options for the second tab, to be decided before any third-party card is allowed in either
region: mount each region's children inside a nested element with its own shadow root (the cost is that `querySelector` from the shell no longer reaches them, and a number of element tests would need a helper),
or run the browser check with that card mounted. This was found by reading the code, not run in Home Assistant, and nothing was changed for it here.

### 16.5 What the owner needs to know

1. **A new attribute write in the card now needs the pin edited in the same commit** (`test/aria-guard.mjs`, `ARIA_PIN`), exactly as a stylesheet change needs the style pin. That is the intended friction.
2. **Adding a new kind of entity to an Intelligence package file now stops the ledger build** until the tool models it. That is the intended behaviour: the alternative was a ledger that said it matched while an
   entity was unaccounted for.
3. The browser check found no defect in the shell itself: the real card passes all 3192 checks. J2 and J5 were never in the card; they were holes in the tests.
4. The decision on child cards (16.4) belongs to the second-tab work. Nothing else changed for the owner: the integration steps of section 8 are unchanged, no pinned or deployed file was edited.

### 16.6 Results of the runs

| Run | Result |
|---|---|
| `node --test test/*.test.mjs` (core 135, element 110, coverage 4, static 41, real-catalogue 157, strip-check 11, mutation proof 215) | 673 of 673 pass; 213 of 213 mutants killed (188 before this round: 25 new, of which 21 aria and 4 spaced-MAC) |
| J2 and J5 against the round-3 suites, then against these | before: 449 of 449 pass on each; after: 4 and 3 of the new tests fail, and the mutation proof kills both |
| `node preview/check-strip.mjs` | PASS: 48 states, 24 Production / Geek pairs, 3192 of 3192 checks (2856 before this round) |
| `node preview/check-strip.mjs --selftest` | SELFTEST PASS: the card passes and 31 of 31 broken copies fail (the 25 of round 3 and the 6 accessibility ones: 72 to 156 failing checks each) |
| the round-3 browser check, then this one, on J2 and J5 (`--card`) | before: PASS 2856 of 2856 on each; after: FAIL, 96 and 72 of 3192 checks |
| `python -I -B -X utf8 frontend/ecco-mode-shell/test/test_example_dashboard.py` | all example-dashboard checks pass |
| `tools/tests/test_geek_mode_{catalogue,coverage,ledger,fixtures,privacy,example}.py` | all pass (110, 168, 60, 102, 149 and 35 checks; coverage gained 56, ledger 8, privacy 3) |
| `tools/geek_mode_coverage.py --check`, `tools/gen_geek_fixtures.py --check` | both match a fresh regeneration (the ledger and the catalogue are byte-identical to before: the tool's walk changed, not its output) |
| `tools/validate_repo.py` | PASSED, with no edit to any pinned file |
| `tools/run_offline_tests.py --root` `tools/tests`, `ecco_core/tests`, `health/tests`, `intelligence/tests` | 21 of 21, 6 of 6, 2 of 2 and 33 of 33 |
| `tools/run_offline_tests.py --root home-assistant/tests` | 18 of 18 |
| `tools/run_offline_tests.py --root registry/tests` | NOT completed: it was still running (33 of 78 suites done) when this record was written. The one failure so far is `test_fallback_durable_host_compile.py`, a suite that needs a C++ compiler this PC does not have (rounds 1 and 2: 76 of 78, the two compiler-dependent suites failing as before). It reads nothing this change touches |

### 16.7 Changes to existing tests (none weakens an assertion)

- `static.test.mjs`: an import line and three tests were appended; one COMMENT in the round-3 literal test was rewritten (it claimed aria-hidden writes were pinned there, and no assertion checked one; it now says where they are pinned).
  Every assertion is unchanged.
- `element.test.mjs`: two tests and three helpers were appended; nothing else changed.
- `core.test.mjs`: the import line also takes `SECRET_VALUES_R4`; three tests were appended.
- `secrets.mjs`: one export was added (`SECRET_VALUES_R4`, 3 values); `hostileAttributes()` and `forbiddenStrings()` carry it, so every existing end-to-end hostile test also runs it.
- `mutations.test.mjs`: 25 mutants and one constant were appended; nothing was removed or changed.
- `strip-check.test.mjs`: the synthetic healthy measurement gained the accessibility attributes it now has to carry (and its builder two constants), one test was appended; every earlier case still fails the check it failed.
- `preview/strip-check.html`, `strip-check-lib.mjs`, `check-strip.mjs`: the page measures the attributes, the judge checks them, the self-test table has six more entries; no existing check was changed.
- `tools/geek_mode_coverage.py`: `_package_entities` was rewritten to fail closed (output unchanged on the real packages: `--check` passes against the committed ledger).
- `test_geek_mode_coverage.py`, `test_geek_mode_ledger.py`, `test_geek_mode_privacy.py`: checks were appended (a block [6] in the first two, a scanner and two checks in the third); one ledger-suite import gained a name.

## 17. Review round 5 (15 Nov 2026): findings and fixes

The fifth review found one MAJOR finding, one MINOR finding in the node tests, one MINOR finding in the Python tool and two NIT findings. Every one of the MAJOR and MINOR findings is a hole in the
**test net**: the card behaved correctly on every input the reviewer tried, and the shipped code changed in only two small places (both NITs). The same rules held: nothing pinned, sealed or deployed was
edited, nothing is live, nothing was pushed. Each finding was reproduced first, by running the reviewer's own mutants and probes against the committed round-4 tree (they survived or misbehaved as
reported); then closed by tests that fail without the behaviour, shown by running the new suites against the round-4 card and by mutants that undo each fix. No assertion was weakened or deleted (section 17.7).

### 17.1 The findings and what was done

| # | Severity | Finding | Fix | Proof |
|---|---|---|---|---|
| 1 | MAJOR | Reviewer mutants R14, R15 and R16 (read only the first 64, 300 or 1000 characters of a string for secrets) survived all five node suites: every hostile value of rounds 1 to 4 sits near the start of its string, so nothing pinned that the card reads a string whole. The probe `probe-r14.mjs` (110 characters of prose, then a secret) showed all five kinds of secret in rows, search, raw view and export under R14 | `test/secrets.mjs` gains the fixtures of section 17.2: eight secret kinds (JWT, IPv4, `password=value`, MAC, e-mail, bearer token, 64-digit hex blob, URL with user info) and two short ones, each placed in a string of at most 4000 characters (the longest the card keeps whole) at four offsets (starts at 100, starts at 1500, ends at 3990, ends at 4000), plus a fifth for the short ones (starts at 3990): 42 texts, with a control (the same strings with the secret replaced by filler are shown whole) and a secret wholly beyond the cap (dropped, and the cut is said). They run on every path: `redactValue`, the snapshot row text, the redacted raw attributes, the search index, the state, both exports (core), and the DOM rows, the open attribute lists, the raw view, the search box, copy and both downloads (element) | 5 new tests in `core.test.mjs`, 1 in `element.test.mjs`; 9 new mutants: R14, R15, R16 as the reviewer wrote them, R17 (last 64), R18 (last 1000), R19 (first 3900), R20 (first 3999), a scan of the middle only, and a raised cap. run against the round-4 suites, seven of the nine survived (R14, R15, R16, R18, R19, R20 and the middle-only scan; R17 and the raised cap were already killed), and the new fixtures pass on the round-4 card, as they must (the card is correct); against these suites all nine are killed, the seven by the three positioned-secret tests (R17 by 13 tests, as before) |
| 2 | MINOR | Five mutants (J13, J14, J20, J21, AR08) were caught only by the opt-in headless-browser check, which prints SKIPPED and exits 0 on a machine with no Chrome: J14 and J20 move the strip inside the shell in Geek Mode, J13 and J21 swap the receiver and name of a pinned `style.setProperty` so that `--ecco-fg` or `--ecco-accent` goes transparent on the shell, AR08 calls `attachShadow` on the strip | Element tests: the strip is a direct child of the shell, the shell's children are exactly title, note, strip, always, Production body, Geek body in both modes through nine scenarios and seven steps each, and the strip has no shadow root (13 planted moves, wraps and duplicates are each reported). The DOM stand-in now lets any element take a shadow root, so AR08 is also seen as behaviour. Static tests: the two `setProperty` calls are pinned by receiver, name and value (`seg`, `--ecco-w`, `String(c[s])`; `ringEl`, `--ecco-p`, `String(ring.pct)`), the receivers are declared once and never reassigned or walked up, and each property is read once by the stylesheet; `attachShadow` is written exactly once, as `this.attachShadow` in the constructor of the card, and no other element may take one | 2 new tests in `element.test.mjs` (the place, and its teeth), 2 in `static.test.mjs`; 12 new mutants (J13, J14, J20, J21, AR08 and 7 variants); run against the round-4 suites 10 of the 12 survived (killed before: a third inline property, and the strip moved into the always region). All five reviewer mutants are killed by the node suites alone. The mutation runner also hands the five to `preview/check-strip.mjs --require --card` when a browser is installed, as a second opinion: all five fail it (120, 204, 48, 12 and 672 checks); where there is no browser that layer is skipped and says so |
| 3 | MINOR | `tools/geek_mode_coverage.py` read only the three `ecco_intel*` package files: mutant L05 (an `input_text` `ecco_intel_zz_probe` in `ecco_dump_limits.yaml`) and L06 (a new package file `ecco_zz_probe.yaml` with a legacy template sensor `ecco_intel_zz_probe`) passed `--check`, `gen_geek_fixtures.py --check` and all six Python suites. The fail-closed fix of round 4 covered the three named files only | `_foreign_definitions` (section 17.3) reads every other YAML file under `home-assistant/` (packages, dashboards, prototypes) and raises a `UniverseError` that names the file and the path for an `ecco_intel_` object id that it defines or names | 32 checks in `test_geek_mode_coverage.py` block [7] (L05 and L06 among 18 refused shapes, 8 shapes that must pass, a negative control and the real tree), 8 in `test_geek_mode_ledger.py` block [7] (L05 and L06 end to end: `--check`, the writer, restored, and a scratch repository with every real YAML file); the reviewer's `ledger_mutants.py` now reports L05 and L06 KILLED by `coverage --check`, `fixtures --check`, the ledger, coverage and fixture suites |
| 4 | NIT | `compileExtra` refused nested quantifiers only: `(a\|aa)*c` was accepted, and a 36-character key of the letter a took 274 ms in `isSecretKey` (time doubles with each character) | Two changes: a pattern reader (`riskyPattern`) refuses a repeated group (`*`, `+`, `{`) that holds an alternation or a repeat, an unbalanced group, an unclosed character class and more than three unbounded repeats; and a catalogue pattern is never run on more than 200 characters of a key (a longer key is read from both ends, so a name at the end of a long key is still found) | 2 new tests in `core.test.mjs` (the reviewer's pattern and 13 others are ignored, 8 sound ones still work, 36, 60 and 5000-character keys cost under 250 ms in all; a spy on `RegExp.prototype.test` sees no run on more than 200 characters, and a name hidden at either end of a 5000-character key is found); 8 new mutants. Against the round-4 card the same probe takes 288 ms at 36 characters; now 0 ms |
| 5 | NIT | `validateConfig` collected `cfg.errors` and nothing showed them: `production` given as text became an empty list and the pause tile vanished with no notice | `setConfig` adds a `shell:config-invalid` warning to the strip, built from the fixed path and message of the first three problems and a count (no value from the configuration is echoed); it goes through the same renderer as the other shell warnings, so the strip itself is unchanged and unconditional | 1 element test (8 kinds of bad configuration, `setConfig` of `undefined`, `null`, a number and text, five problems at once with the catalogue warning beside it, a later good `setConfig` clears it and returns to Production; the strip's accessibility and place checks pass under the warning), 1 core test (the paths and messages); 2 new mutants |

### 17.2 The positioned secrets, and what they do and do not show

Why these offsets: `LIMITS.stringCap` is 4000 and a longer string is cut **before** it is read, so 4000 characters is the longest text the card reads. The four placements are the owner's 100 and 1500,
and the two ends of that range: the secret **ends** at offset 3990 (so the last ten characters are filler), and at 4000 (the last characters of a 4000-character text). A secret cannot *start* at 3990 and fit, except the
two that are ten characters or fewer (a dotted address of ten characters and an e-mail address of eight, both assembled from fragments in `secrets.mjs`), which also start at 3990. A space (or the end of the text) sits on each side, so the word-boundary rules of the card are not helped or hindered. The filler is
prose with no digit, address or key, and every fixture is assembled from fragments like the earlier ones (no committed file holds a secret-shaped text; the privacy suite and the folder scan pass).

The control matters as much as the cases: a redactor that withholds every long text would pass them. The same 42 strings with the secret replaced by filler of the same length must come out whole, and a harmless long text with
four marker words (at 100, 1500, 3950 and the end) must be found by search at every offset and appear whole in the raw view, the copy and the exports: so a search that finds nothing for a secret is the withholding, not a short index.

Still shown, found while writing this and **not changed**: a secret that **straddles** the cap. The card keeps the first 4000 characters and reads those; the part of the secret inside them is shown if it no longer matches a rule
(`someone@ex`, `eyJhbGciOi`, `password=p`, `172.16.88.`, `de:ad:be:e`, `Bearer zyx`, `b3a1c0de5e`; a URL with user info is still withheld). That is at most the ten or so characters before the cap. Reading a little past the cap
before cutting would close it, at the price of withholding a text whose secret lies in the part that is dropped anyway; that is a decision for the owner and is not made here.
**Closed in review round 6, by the owner's direction ("redact first, then truncate"): a string is now read whole, up to 20000 characters, before it is cut; a secret that crosses the cap, or lies beyond it, withholds the whole text (section 18.6).** The paragraph above describes the round-5 card.

### 17.3 The package scan reads content, not names

Round 4 made the three Intelligence package files fail closed, and refused a fourth file whose NAME starts with `ecco_intel`. L05 and L06 are the other way in: an entity in a file that has a different name. `_foreign_definitions`
(called from `_package_listing`, so by every build, `--check`, the writer and the fixture tool) reads every `.yaml` and `.yml` file under `home-assistant/` except the three modelled ones, and refuses:

- a mapping **key** at any depth that is an `ecco_intel` object id, with or without a domain (`input_text.ecco_intel_zz`: a helper, a legacy template sensor, a script, a group, a customize entry);
- a `unique_id`, `object_id` or `default_entity_id` value that is one;
- in a package (not in a dashboard, where `name:` is only a label), a `name` or `alias` whose slug is one (`ECCO Intel zz probe`).

It passes: a reference (an `entity_id:` value, a template, a card's `entity:`), a dashboard label, the other family (`ecco_intelligence_*`, the prototype mock package), and a key under `button_card_templates` or
`decluttering_templates` (the prototype dashboard's own template library `ecco_intel_block`, the one false positive the real tree had). A file that does not spell `ecco`, an optional separator and `intel` is **not parsed**
(it cannot define such a name), so the cost is a text search per file and a parse of the five files that mention it: 21 files, 0.22 s on this PC. A file that does spell it and does not parse is refused too. What it cannot
see: a name built by a template or spelled with YAML escapes, a definition made outside `home-assistant/` (the integration's own entities are read from code), and any file that is not YAML.

When the scan refuses, the message says what to do: model the file (add it to `PACKAGE_FILES` and read it in `_package_entities`) and catalogue it, or, for something that is not an entity, add its parent key to `NON_ENTITY_PARENT_KEYS`.

### 17.4 The catalogue's key patterns

`redaction.extra_key_patterns` are written by the catalogue's owner (the Intelligence ones are plain lower-case fragments), but a catalogue is data and a pattern is code, so the card screens them. A pattern is **ignored**, never
thrown, when `riskyPattern` refuses it: that is the same outcome as the earlier rules (too long, a back-reference, nested repeats, invalid), and means a key it was meant to withhold is not withheld by it. The reader skips
escapes and character classes (so `^[(|]+$` is fine), tracks groups, and refuses a repeated group that holds a repeat or an alternation (`(a|aa)*c`, `(x+x+)+y`, `((a+))+b`, `(a|b){2,}c`), an unbalanced pattern, and more
than three unbounded repeats (`a*a*a*a*b` is polynomial, of a high degree). With the 200-character cap that bounds the work of any accepted pattern: at most a cubic in 200, a few milliseconds. It errs towards refusing:
`(ab?)+` is refused too. An owner who needs one of these shapes should write the keys out instead.
**Superseded in review round 6 (section 18.5): a catalogue key pattern is now a plain fragment and no expression is accepted at all; `riskyPattern` and `EXTRA_MAX_REPEATS` no longer exist, and a long key is searched in overlapping windows of 200 characters, not read from both ends.** This section describes the round-5 card.

### 17.5 What the owner needs to know

1. **Nothing the owner has to do.** No pinned, sealed or deployed file was edited, and no integration step of section 8 changed.
2. The shipped card changed in two places only, both small: the strip warning for a bad card configuration (a view whose `production` list was silently empty now says so on the strip, in both modes) and the screening of catalogue key patterns.
3. `tools/geek_mode_coverage.py` is now stricter: a new `ecco_intel_` entity in **any** Home Assistant YAML file stops the ledger build until it is modelled. That is the intended behaviour, as in round 4.
4. The strip's place in the shell, its two inline-style sites and the single `attachShadow` are now pinned by the node suites: a person who changes one edits the pin in the same commit. The browser check stays the extra layer, and the mutation runner uses it when there is a browser.
5. The straddling-secret limit of 17.2 is a decision for the owner (read past the cap, or accept at most the characters before it).

### 17.6 Results of the runs

| Run | Result |
|---|---|
| `node --test test/*.test.mjs` (core 143, element 114, coverage 4, static 43, real-catalogue 157, strip-check 11, mutation proof 252) | 724 of 724 pass in 331 s; 244 of 244 mutants killed by the node suites (213 before this round: 31 new); the mutation proof also hands five of them to the browser check on this PC (Chrome is installed) and all five fail it |
| the five reviewer mutants of the finding 2 (J13, J14, J20, J21, AR08) and R14, R15, R16, run against the round-4 suites and the round-4 card | all eight SURVIVED (the reviewer's reproduction, repeated here); L05 and L06 against the round-4 tool: `--check` exit 0, "match a fresh regeneration"; the reviewer's `probe-redos.mjs`: 288 ms at 36 characters |
| the 31 new mutants against the round-4 suites, then against these | of the 21 that can be applied to the round-4 card (the other 10 undo code that did not exist: the pattern reader, the cap, the configuration warning) 17 SURVIVED the round-4 suites (7 of the 9 that read part of a string, 10 of the 12 that move the strip or change an inline property or a shadow root); all 31 are KILLED by the node suites alone, with no browser |
| the new tests run against the round-4 card (`ECCO_MODE_SHELL_PATH` at a copy of it) | 3 fail there: the two NIT-1 tests in `core.test.mjs` (the pattern reader, the 200-character cap) and the NIT-2 test in `element.test.mjs` (the configuration warning); the positioned-secret, placement and pin tests pass there, as they must (the round-4 card is correct): they are shown by the mutants |
| `node preview/check-strip.mjs`, `--selftest` | PASS: 3192 of 3192 checks (unchanged: the strip, its places and attributes are as before); SELFTEST PASS: the card passes and 31 of 31 broken copies fail |
| `python -I -B -X utf8 frontend/ecco-mode-shell/test/test_example_dashboard.py` | all example-dashboard checks pass |
| `tools/tests/test_geek_mode_{catalogue,coverage,ledger,fixtures,privacy,example}.py` | all pass (110, 200, 68, 102, 149 and 35 checks; coverage gained 32, ledger 8) |
| `tools/geek_mode_coverage.py --check`, `tools/gen_geek_fixtures.py --check` | both match a fresh regeneration (the ledger, the catalogue, the shape and the fixtures are byte-identical to before: the tool's walk changed, not its output) |
| the reviewer's `ledger_mutants.py` L05 and L06 | KILLED (before: SURVIVED): `coverage --check`, `fixtures --check`, the ledger, coverage and fixture suites fail; the privacy suite does not (it reads fixtures, not packages) |
| `tools/validate_repo.py` | PASSED, with no edit to any pinned file |
| `tools/run_offline_tests.py --root` `tools/tests`, `ecco_core/tests`, `health/tests`, `intelligence/tests`, `home-assistant/tests` | 21 of 21, 6 of 6, 2 of 2, 33 of 33 and 18 of 18 |
| `tools/run_offline_tests.py --root registry/tests` | 76 of 78 pass in 1104 s; the two failures are `test_fallback_durable_host_compile.py` and `test_rtc_policy.py`, each with the single check "a C++ compiler is available" (this PC has no C++ compiler; the check fails rather than skips). Both fail identically on a copy of the round-4 tree, and they read nothing this change touches (rounds 1 and 2: the same two) |

### 17.7 Changes to existing tests and files (none weakens an assertion)

- `core.test.mjs`: an import line and eight tests were appended; nothing else changed. `element.test.mjs`: four tests and helpers were appended. `static.test.mjs`: two tests were appended. `mutations.test.mjs`: 31 mutants, two constants, the import of
  `findBrowser`, and the optional browser layer were added; nothing was removed or changed, and the anchors of the existing mutants are untouched (the new code was written around the lines they target).
- `secrets.mjs`: the positioned-secret fixtures were appended (nothing existing changed; `hostileAttributes()` and `forbiddenStrings()` are unchanged, so no existing test sees the new values).
- `minidom.mjs`: `attachShadow` is now a method of every element (before, only the card's host had it). No existing test was affected.
- `ecco-mode-shell.js`: `riskyPattern`, `EXTRA_KEY_CAP`, `EXTRA_MAX_REPEATS`, `configProblemText`, the 200-character screening in `isSecretKey` and the `shell:config-invalid` alert (existing lines are unchanged; the old nested-repeat test in `compileExtra` is kept and the new reader is in addition to it).
- `tools/geek_mode_coverage.py`: `_package_listing` calls the new `_foreign_definitions`; its output on the real tree is unchanged (`--check` passes against the committed ledger and catalogue, byte for byte).
- `test_geek_mode_coverage.py`, `test_geek_mode_ledger.py`: a block [7] was appended to each. `tools/tests/_geek_scratch.py`: a comment only.
- **No pin and no fixture was regenerated** (`style.pin.json` and the generated catalogue, ledger, shape and fixtures are byte-identical to round 4; the card's stylesheet and its 18-site attribute pin did not change).

## 18. Review round 6 (15 Nov 2026): findings and fixes

The sixth review found two MAJOR findings and one MINOR finding in the node tests, one MINOR finding in the Python tool and two NIT findings (one of them the straddling-secret limit that section 17.2 left to the owner). The card behaved correctly on every input the
reviewer tried: both MAJOR findings and both MINOR findings are holes in the **test net**; the two NITs are small changes to shipped code. The direction of this round was different from the earlier five, each of which closed the reviewer's named instance and was followed by a new
instance of the same class: **close the class**. Each finding was reproduced first, against the committed round-5 tree, by running the reviewer's own mutants and probes (they survived or misbehaved exactly as reported, section 18.8); then closed by tests that fail without the behaviour,
shown by running the new suites against the round-5 card and by mutants that undo each fix. Nothing pinned, sealed or deployed was edited, nothing is live, nothing was pushed. No assertion was weakened or deleted (section 18.9 says exactly what was changed, and why each change is the new rule and not a loosening).

### 18.1 The findings and what was done

| # | Severity | Finding | Fix | Proof |
|---|---|---|---|---|
| 1 | MAJOR | Reviewer mutants S01 (a text of more than 1000 characters is read from its second character), S02 (only the last 3999 characters are read), S06 and S07 (the text is read in chunks of 500 or 1000 characters with no overlap) survived all five node suites. The round-5 placements start at 100, 1500 and 3990 and end at 3990 and 4000, so none put a secret at offset 0 of a long text or across a likely chunk edge | The **sweep** (section 18.3): every kind of secret (12: the eight and the two short ones of round 5, and two whose own text holds a newline or spaces) at **every offset** (the short kinds) or at every boundary neighbourhood plus a stride of 37 (the others), in carriers of 1500, 3999, 4000 and 4500 characters (12000 and 20000 sparsely), on every path: `redactValue` (bare, nested, in a list, under a revision key), the snapshot rows, the redacted raw attributes, the search index, the state, both exports, key names, and the DOM (rows, raw view, search box, copy, row copy, both downloads). A control proves the same carriers without the secret are shown whole, or cut with the cut said | 7 new tests in `core.test.mjs`, 1 in `element.test.mjs`; 23 new mutants (20 that read part of a string: S01 to S08; chunks of 256, 1024 and 4000 with no overlap and of 500 and 1000 with a 20 and a 40-character overlap; the first 4000, the first and the last 19999 characters; ends only; a middle window; off by one at either end. 3 that read part of a key name). Against the round-5 suites S01, S02, S06, S07 SURVIVED (S03, S04, S05, S08 were killed); against these all ten are killed |
| 2 | MAJOR | Mutant K02 (`const tail = whole`) survived: with one accepted pattern `a*a*a*b` and a 1200-character key the real card took 388 ms and K02 59852 ms; 40 accepted three-repeat patterns cost 4350 ms per long key in the real card (`riskyPattern` accepts them) | **Plain fragments** (section 18.5): `redaction.extra_key_patterns` accepts only `^[a-z0-9_]{1,80}$` (what the Python tool emits), at most 40, matched as a part of the key name; **no RegExp is built from catalogue data at all**, so there is no backtracking question, and `riskyPattern` is gone. The 200-character cap is kept as the size of one search; a longer key is read in overlapping windows, so every part of it is read (round 5 read the first and the last 200 characters only); a key longer than the bound is withheld. The Python validator and tests carry the same rule | 4 new tests in `core.test.mjs` (a fragment of 1, 8 and 80 characters at every offset of every key up to 260 characters and at every window edge of longer ones up to 20000; what is accepted and refused; a spy that no search sees more than 200 characters; the bound) and 2 rewritten round-5 tests; 1 in `static.test.mjs` (one RegExp in the code, the fragment rule is one literal, read before cut); 19 new mutants including K02 (whole key, unbounded slice, window of 500, no overlap, overlap one short, head only, tail only, ends only, case, an expression built from data); 8 round-5 mutants of the pattern reader were retired (section 18.9); the Python catalogue suite gained 24 checks, and 10 Python mutants of the rule are killed |
| 3 | MINOR | Mutant P07 (`...parentNode.style['setProperty']('--ecco-fg', 'transparent')` next to the bar-segment call) survived: the count of `.style.setProperty(` stays two and the bracket form escapes the `.style.name` scan; only `check-strip --require` failed it | The pin is now **structure, not spelling** (section 18.4): the word `style` appears in the code only as the receiver of the two pinned calls and in the three statements that build the card's one `<style>` element; `setProperty` is written twice; no computed access, alias, destructuring, built name, `cssText`, `Object.assign`, CSSOM, `adoptedStyleSheets` or other door exists. The same net **by behaviour**: after every kind of update, in both modes, the only elements that carry an inline custom property are the bar segments (`--ecco-w`) and the rings (`--ecco-p`) | 3 tests in `static.test.mjs` (one with 11 planted forms, each refused), 1 in `element.test.mjs` (with negative controls on the shell, the strip and the host); 8 new mutants (P04, P05, P06, P07, P08 and three more forms); P07 is marked `browser: true`, so the mutation runner hands it to the headless check too, which fails it |
| 4 | MINOR | `tools/geek_mode_coverage.py` decided a file was a dashboard if it held a `views` key (N-L11: a new package file `ecco_zz_views.yaml` with `views: []` and a template sensor `ECCO Intel zz probe` passed `--check`, the fixtures `--check` and all Python Geek suites) | A dashboard is decided by **where the file is**: a file under `home-assistant/dashboards/`, the one named prototype dashboard, or the file the dashboard registration (`lovelace: dashboards: ... filename:`) points at; a registration that points into `packages/` or out of the repository is refused; a top-level `views:` key in any file under `home-assistant/packages/` is refused (as text, and as a parsed key for a file written in flow style) | 19 new checks in `test_geek_mode_coverage.py` block [8] (N-L11 in three spellings, a package with a views key that does not spell the name, the control without it, the same file under `prototypes/`, the registration cases, the real tree); against the round-5 tool 9 of them FAIL and the module has no `DASHBOARD_DIR_REL`; 11 Python mutants of the rule are killed (section 18.8) |
| 5 | NIT | A refused or invalid catalogue pattern was dropped silently: `(site\|home)+_owner` gave `ok: true` with no error and `home_owner` showed its value | Every pattern that is not a plain fragment is a **catalogue error** at its own place (`redaction.extra_key_patterns[i]`, a fixed message that echoes nothing), as is a list of more than 40 (the per-pattern errors are bounded: a list of a hundred thousand bad patterns makes 41) and a list that is not a list. The strip shows it (the catalogue warning is unconditional) and the inventory is switched off, as for any invalid catalogue | the plain-fragment test in `core.test.mjs` (24 refused forms, 6 non-text values, the place of each error, the sanitised copy, 40 and 41 patterns, a list that is not a list); 5 mutants (a refused pattern dropped in silence, more than forty dropped in silence, a non-list ignored, the sanitised copy keeping a refused pattern, the errors not bounded) |
| 6 | NIT | A secret that straddles the 4000-character cap could leave about ten characters of itself before the cap (section 17.2) | **Read first, cut after** (section 18.6): a string is read whole, up to `LIMITS.scanBound` (20000 characters), and only then cut at the display cap, so a secret that crosses the cap, or lies wholly beyond it, withholds the whole text; a string longer than 20000 characters is not read in part, it is withheld whole, and the marker's tooltip now says so | `core.test.mjs`: every kind at every start from three characters before the secret would end at the cap to three after it, in seven carriers (2,261 cases); the reviewer's picture (a ten-character address starting at 3995); a text of exactly 20000 characters is read and cut, one of 20001 is withheld, a 600000-character text costs a length test; `element.test.mjs`: the marker's tooltip; 9 mutants (truncate before read, no bound, bound raised, bound lowered, bound off by one, the first 20000 read and the rest dropped, a key bound dropped or raised, a tooltip that claims the value is secret) |

### 18.2 The classes closed

A class is closed when **any** shape of the break, not only the reviewer's, fails a test. This is what the round closes, in the order it was done.

1. **Redaction scan coverage** (findings 1 and 6): "every character of every string is read, whatever shape the scan has". The sweep puts each kind at every offset that matters and fails any prefix, suffix, window, chunk (with or without an overlap), middle, ends-only, per-line, split-by-space or off-by-one reader of a string. The key-name scan (the first 200 characters, of which 120 are ever shown) has its own sweep, because the same shape of break could sit there.
2. **Code from data** (findings 2 and 5): no RegExp is built from catalogue data; a pattern is a plain fragment or a catalogue error. The question "can this pattern run for long" cannot be asked of a substring search, and a static test pins that the code names `RegExp` once.
3. **A key read in windows** (finding 2): a key is read in windows of at most 200 characters that overlap by one less than the longest fragment, so the work of one search is bounded and no part of a key is skipped; a fragment at every offset of every key up to 260 characters, and at every window edge of longer ones, is found; a key longer than the bound is withheld.
4. **Inline-style writes** (finding 3): the structure of the source (the word `style`, `setProperty`, computed access, built names, every other door) and the behaviour (which elements ever carry an inline property) are both pinned, so the next spelling is either a structure change or a behaviour change.
5. **A dashboard decided by content** (finding 4): by location, with a refusal of a package that carries `views`.
6. **The order of the cut and the read** (findings 6 and 1): read first, cut after, with a hard bound and the whole text withheld beyond it; a static test pins the order inside `redactString`, and the straddle sweep proves it at the display cap.
7. **Quadratic reads at a larger input** (found while closing 6, not a finding): reading a text whole up to 20000 characters instead of 4000 made three rules that read ahead from every start position (a dotted host name, a dotted MAC address, a pass pair) cost about a quarter of a second on one 20000-character text that only looks like the start of one (`a.a.a...`, `xy-xy-...`). Each now has a **pre-test**, a linear test every match must pass (a necessary condition, so the verdict is the same). A table of its own holds them, so the three rules stay byte-identical with the Python scanner's patterns (the privacy suite compares them). A test asserts five such texts cost under 150 ms between them (about 1 ms with the pre-tests, about 700 ms without), and a second test asserts every shape the three rules matched before is still withheld; 7 mutants (a pre-test dropped, too strict, never asked, shifted by a row).

### 18.3 The sweep

**Carriers.** 1500 (the reviewer's), 3999 and 4000 (just under and at the display cap), 4500 (over it, so the text is cut for display and a secret may cross the cut), and 12000 and 20000 (the longest the card reads) for the sparse sweep. Each carrier is built by
`carrier(value, start, total)`: filler prose with no digit, address or key, then the secret starting at exactly `start`, then filler, a space on each side when there is room (so no word-boundary rule is helped or hindered), the text exactly `total` characters (the function throws if it is not).

**Kinds (12).** The eight of round 5 (JWT, IPv4, `password=value`, MAC, e-mail, bearer token, 64-digit hex blob, URL with user info), its two short ones (a ten-character address, an eight-character e-mail address), and two new ones whose own text holds a newline (`password=` newline `value`) or spaces
(`password = value`), which a per-line or a split-at-spaces reader misses. Every value is assembled from fragments, as before (no committed file holds a secret-shaped text; the privacy suite and the folder scan pass).

**Offsets.** A kind of 24 characters or fewer is "short" (eight of the twelve): it is swept at **every offset** of every carrier (stride one). The others are swept at every start at which the secret ends before, ends at, crosses, begins at or begins after each of the boundaries
0, 1, 2, 255, 256, 257, 499, 500, 501, 511, 512, 513, 999, 1000, 1001, 1023, 1024, 1025, 2047, 2048, 2049, 3990, 3999, 4000 and 4001 (three either side), at a stride of 37 across the whole carrier, and at the last four starts that fit (the secret ends the text).

**Cases.** 117,603 on the core path (`redactValue` of a bare string under an innocent key, four carriers); 6,067 more in the 12000 and 20000 carriers (stride 997 and the boundaries); 2,821 boundary starts in all six carriers through every other door of the core (no key, a dict value, a list item, an attribute object, a revision key, with the catalogue's fragments); 1,743 of them through the snapshot (row, state, raw attributes, search index, both exports, the harmless control); 3,275 key names (every kind at every offset of a 300-character key); 2,261 straddles of the display cap; and 204 DOM cases (the start, across 500, across 1000, across the display cap, the very end), checked as a person sees or takes the text away: the rows, the open attribute lists, the raw view, the search box, copy, row copy and both downloads.

**What it cannot see.** A reader that is correct everywhere the sweep looks and wrong somewhere else: for instance one that skips a window only in a text of a length the carriers do not have (the lengths tested are 1500, 3999, 4000, 4500, 12000, 20000 and the over-bound ones, and the starts include the ends of every one), or one that is wrong only for a kind of secret the card has no rule for. The sweep proves that every rule the card has is applied to every character; it does not prove the rules are complete (sections 15.3 and 16.4 list what the redactor does not catch).

### 18.4 The inline-style pin, by structure and by behaviour

The round-5 pin read the two literal sites of `.style.setProperty(` and counted them. P07 added a third, spelled with a bracket, so the count of the spelling it knew did not change. The pin now reads what the **word** `style` is attached to: outside the stylesheet text it
appears exactly seven times, in the two pinned calls (receivers `seg` and `ringEl`, bare locals made once and never reassigned) and in the three statements that build the card's one `<style>` element; `setProperty` is written twice; there is no `[` after a style, no string that spells it, no name built
from pieces (`'sty' + 'le'`, a template), no `cssText`, `attributeStyleMap`, `adoptedStyleSheets`, `insertRule`, `getComputedStyle`, `Object.assign` onto a style, `dataset`, `classList` or `className`. Eleven planted forms (the bracket call, an alias, a computed key, `cssText`, `Object.assign`, a property write, a third call, a
destructured style, a template-built name, a bracket call on a built name, a join) are each refused by these rules, and the real source passes them. The element suite adds the net that does not read the source: it walks the rendered tree in both modes, after a first render, a mode switch, an update that raises an alert and a switch back, and asserts the only
elements that carry an inline custom property are bar segments (`--ecco-w`) and rings (`--ecco-p`), with the host, the shell and the strip carrying none; properties planted on the shell, the strip and the host are each seen. A static read of source cannot exclude every spelling (a name built at run time), which is why the behaviour net and the headless browser check stand behind it.

### 18.5 The catalogue's key patterns, again

Section 17.4 described a reader of expressions that refused the shapes known to run for long. The round-6 reviewer showed that a screen of a language is a whack-a-mole of its own (40 three-repeat patterns passed it), and it is not needed: the Python tool only ever emits fragments. The rule now is one literal, `^[a-z0-9_]{1,80}$`, at most 40 per catalogue, matched as a part of the key
name after the key is folded and lower-cased. **Narrowing, stated plainly:** anchors (`^x$`), classes, groups, alternation and repeats are not accepted any more; a pattern that holds one is a catalogue error, not a pattern that does something else. The tests that used richer expressions (`^site_owner$`, `^zzhead`, `zzmark$`, `^(?:foo|bar)_key$`, `^[a-z]+_(?:token|secret)$`, `^zz(?:ab|cd)?x$`, `a*b*c*d`) were
rewritten to the fragment each meant and **kept as refusal cases** in the form they had (each old pattern is still listed, must still be ignored by the redactor, and must now be reported), so no coverage was dropped; the one fixture that held one (`mini.catalogue.json`: `^site_owner$`) now holds `site_owner`. A fragment matches wherever it lies in a key (`owner` withholds `my_owner_name`), as the round-5 patterns without anchors already did. If the owner ever needs "this key and no other", the answer is to write the keys out, as section 17.4 said.

A catalogue with a refused pattern is **invalid**, so the strip says so (the existing `shell:catalogue-invalid` warning) and the Geek Mode inventory is switched off until it is fixed, the same fail-closed behaviour as for any other catalogue error. Production Mode and the alert strip are untouched. The Python tool applies the rule with `fullmatch`: a Python `$` also accepts a newline at the end, so `token` followed by a newline would have passed the old check (a test pins it).

### 18.6 Read first, cut after: what a person sees now

- A text of up to 4000 characters is shown whole, as before.
- A text of 4001 to 20000 characters that holds no secret is shown cut at 4000 with the cut said (`... [truncated N more characters]`), as before.
- A text of 4001 to 20000 characters that holds a secret **anywhere**, including past character 4000, is **withheld whole** (the row says "Withheld"). Before: a secret past 4000 was dropped by the cut and the text shown, and a secret across the cut left a part of itself.
- A text of more than 20000 characters is **withheld whole**, with or without a secret (before: shown, cut at 4000). The marker is the same `[withheld]`; its tooltip now says "it looks secret or private, or it is too long to be checked", so the words are true for both causes. A genuinely long, harmless text is therefore not shown at all in Geek Mode; if the Intelligence entities ever carry one, the owner can raise `LIMITS.scanBound` (and re-run the performance tests) and the sweep follows it.
- A key name of more than 20000 characters withholds its value.

### 18.7 What the owner needs to know

1. **Nothing the owner has to do.** No pinned, sealed or deployed file was edited, and no integration step of section 8 changed.
2. The shipped card changed in five places: redaction reads before it cuts (and withholds a text longer than 20000 characters), a catalogue pattern is a plain fragment and a refusal is shown, a key is read in overlapping windows, three read-ahead rules have pre-tests, and the tooltip of the withheld marker. Production Mode is unchanged.
3. `tools/geek_mode_coverage.py` is stricter again: a package file that carries a top-level `views:` key stops the ledger build, and so does a dashboard registration that points into `packages/`. On the real tree nothing changes (`--check` passes byte for byte).
4. A catalogue written for the round-5 card with a regular-expression pattern now needs rewriting as fragments; the Intelligence catalogue already was (`config_hash`, `entities`, `git_sha`, `latitude`, `longitude`).
5. Observation, **not changed**: `SOURCE_ID_RE` and the other `^...$` patterns of the Python validator use `match`, which accepts a newline at the end of a value. Only the new fragment rule was made exact, because it is the only one a card then matches as text.
6. Observation, **not changed**: the work of one redaction call is bounded by 20000 values (`LIMITS.nodes`) of at most 20000 characters (`LIMITS.scanBound`) each, so a hostile entity could still make one rebuild read up to 400 million characters (80 million before this round); there is no total-character budget per entity. The 5000-entity budgets are green, the shapes that made single texts quadratic are closed (class 7), and a total budget (which would replace the later values of one entity with `[more values omitted]`) is a small follow-up if the owner wants hostile attribute data bounded as well.
7. Observation, **not changed**: the registry suite (`registry/tests`, 18 minutes, two known compiler-dependent failures on this PC) was not re-run in this round: it reads nothing this change touches.

### 18.8 Results of the runs

| Run | Result |
|---|---|
| `node --test test/*.test.mjs` (core 157, element 117, coverage 4, static 47, real-catalogue 157, strip-check 11, mutation proof 316) | 809 of 809 pass in 404 s (the mutation proof is 316 of them); 307 of 307 mutants are killed by the node suites alone; the mutation proof also hands six of them (J13, J14, J20, J21, AR08, P07) to the headless check on this PC (Chrome is installed) and all six fail it |
| the 307 mutants (244 before; 8 retired, 71 added) | 307 of 307 KILLED by the node suites alone; the mutation proof also hands six of them (J13, J14, J20, J21, AR08 and P07) to the headless check on this PC (Chrome is installed) and all six fail it |
| the reviewer's own mutants S01, S02, S06, S07, K02 and P07, run against the round-5 suites (the committed tree) | all six SURVIVED, as reported (S03, S04, S05 and S08 were killed); against these suites all ten are KILLED |
| the reviewer's probes against the round-5 card | `home_owner`: `validateCatalogue` `ok: true`, 0 errors, the value shown; a ten-character address starting at 3995 of a 4600-character text: not withheld, the text shown as `...10.2... [truncated 607 more characters]`; N-L11: the package with `views: []` and a template sensor `ECCO Intel zz probe` passes `_package_entities` |
| the new node suites run against the round-5 card (`ECCO_MODE_SHELL_PATH` at a copy of it) | 19 of 482 tests FAIL there: the sweep (4 in core, 1 in element), the cap straddle, the bound, the four fragment tests, the tooltip, the performance test, the static fragment test, the two rewritten round-5 tests, and the three tests whose input size now uses `LIMITS.scanBound`, which the round-5 card does not have; the inline-style tests pass there, as they must (the card is correct): they are shown by the mutants |
| `node preview/check-strip.mjs --require`, `--selftest` | PASS: 3192 of 3192 checks (unchanged: the strip, its places and attributes are as before); SELFTEST PASS: the card passes and 31 of 31 broken copies fail |
| `tools/tests/test_geek_mode_{catalogue,coverage,ledger,fixtures,privacy,example}.py` | all pass (134, 219, 68, 102, 149 and 35 checks; catalogue gained 24, coverage 19) |
| the new Python tests run against the round-5 tool | the catalogue suite fails 16 checks and stops at `PATTERN_MAX_COUNT`; the coverage suite fails 9 and stops at `DASHBOARD_DIR_REL` |
| 21 mutants of the Python tool (the old rule, everything a dashboard, each check removed, the registration ignored, into `packages/`, out of the repository, the prototype list emptied, the pattern limits, `match` for `fullmatch`, ...) | 21 of 21 KILLED by the coverage and catalogue suites |
| `frontend/ecco-mode-shell/test/test_example_dashboard.py` | all example-dashboard checks pass |
| `tools/geek_mode_coverage.py --check`, `tools/gen_geek_fixtures.py --check` | both match a fresh regeneration (the ledger, the catalogue, the shape and the fixtures are byte-identical to before: the tool's walk and the validator changed, not their output) |
| `tools/validate_repo.py` | PASSED, with no edit to any pinned file |
| `tools/run_offline_tests.py --root` `tools/tests`, `ecco_core/tests`, `health/tests`, `intelligence/tests`, `home-assistant/tests` | 21 of 21 (237 s), 6 of 6, 2 of 2, 33 of 33 (264 s) and 18 of 18 (1118 s) suites pass; registry/tests was not re-run (observation 7 of section 18.7) |
| measured, this PC | a text of 20000 characters that only looks like a host name, a MAC address or a pass pair cost about 80 to 255 ms each without the pre-tests, and three of them cost 1.3 ms with them; a snapshot of 2000 entities with a harmless 4500-character text each: 200 ms in round 5, 241 ms now; the 5000-entity budgets of AC12 are green |

### 18.9 Changes to existing tests and files (none weakens an assertion)

- `ecco-mode-shell.js`: `riskyPattern` and `EXTRA_MAX_REPEATS` were removed (nothing is an expression any more), `compileExtra`, `isSecretKey`, `redactString`, `validateCatalogue` and `valueReason` changed as described, `LIMITS.scanBound`, the exported constants `EXTRA_FRAGMENT_MAX` and `EXTRA_FRAGMENTS_MAX`, `RULE_PRETESTS`, and the tooltip text of the withheld marker were added. The `RULES` table is byte-identical, and so is the stylesheet.
- `core.test.mjs`: appended: 15 tests (the sweep group, the fragment group, the pre-test group); changed, each for the new rule and with every assertion kept: the constant `EXTRA` and one test now use `site_owner` instead of `^site_owner$` (the same key, as a fragment); the two tests of huge values (`AC10 redaction: huge values and structures...`, `AC12 caps: an attribute far larger than the cap...`) use a text of `LIMITS.scanBound - 1` characters instead of 200000 and 600000, because a text beyond the bound is now withheld whole (that case has its own [r6] test, with the 200000 and 600000-character texts); the round-5 test of a secret wholly beyond the cap was rewritten (the text is withheld whole; every assertion it made about what the output holds, the cut said and the length, is made on the same text without the secret, and the one assertion that said a text with a secret beyond the cap is NOT withheld is reversed, by the owner's direction "redact first, then truncate": it is the behaviour that finding 6 changes); the round-5 test of refused expressions keeps its 14 patterns and each assertion (ignored, and the control that the expression does match) and adds that each is a catalogue error, and its "sound" patterns are the fragments they meant; the round-5 test that spied on `RegExp.prototype.test` for a 200-character limit is replaced by one that spies on `String.prototype.includes` (the fragment search) with the same limit, and a name hidden at either end of a 5000-character key is still found.
- `element.test.mjs`: appended 3 tests; one input size changed (`'z'.repeat(300000)` to `LIMITS.scanBound - 1`) in `AC12 caps: a huge attribute is truncated with a marker in the DOM too`, assertions kept.
- `static.test.mjs`: appended 4 tests; nothing changed.
- `secrets.mjs`: appended the sweep fixtures; `hostileAttributes()` and `forbiddenStrings()` are unchanged, so no existing test sees the new values.
- `mutations.test.mjs`: 71 mutants appended. **Retired: 8**, because the code they undo no longer exists: `AC10-r5-extra-key-uncapped`, `-key-tail-unread`, `-risky-guard-dropped`, `-alternation-allowed`, `-alternation-not-propagated`, `-repeat-not-propagated`, `-repeat-count-dropped`, `-class-not-skipped` (the successors are the 10 key-window mutants and the 9 fragment-rule mutants of finding 2). **Re-anchored: 2**, with the same intent: `AC10-extra-patterns-ignored` (the line it removes moved into `keyHasFragment`'s caller) and `AC10-pass-pair-colon-prose` (the break also relaxes the pass pair pre-test, which a necessary condition of the original rule would otherwise hide). The anchors of every other existing mutant are untouched.
- `test/fixtures/mini.catalogue.json`: hand-edited, not generated: `^site_owner$` became `site_owner` (the rule). **No pin and no generated file was regenerated:** `style.pin.json`, the generated catalogue, ledger, live shape and fixtures are byte-identical to round 5 (`--check` of both tools passes), and the 18-site attribute pin did not change.
- `README.md`: the whole-string reading, the key patterns, the test table and the mutant count (307).
- `tools/geek_mode_coverage.py`: `PATTERN_RE`, `PATTERN_MAX_COUNT`, the validator's pattern check, `DASHBOARD_DIR_REL`, `PACKAGES_DIR_REL`, `PROTOTYPE_DASHBOARD_RELS`, `VIEWS_KEY_RE`, `_registered_dashboard_files` and the changed decision in `_foreign_definitions`; its output on the real tree is unchanged.
- `test_geek_mode_catalogue.py`: 15 refused forms, 5 accepted forms and 4 checks were appended; `test_geek_mode_coverage.py`: a block [8] was appended. Nothing existing changed.
