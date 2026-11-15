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
7. **Quadratic reads at a larger input** (found while closing 6, not a finding): reading a text whole up to 20000 characters instead of 4000 made three rules that read ahead from every start position (a dotted host name, a dotted MAC address, a pass pair) cost about a quarter of a second on one 20000-character text that only looks like the start of one (`a.a.a...`, `xy-xy-...`). Each now has a **pre-test**, a linear test every match must pass (a necessary condition, so the verdict is the same). A table of its own holds them, so the three rules stay byte-identical with the Python scanner's patterns (the privacy suite compares them). A test asserts five such texts cost under 150 ms between them (about 1 ms with the pre-tests, about 700 ms without), and a second test asserts every shape the three rules matched before is still withheld; 7 mutants (a pre-test dropped, too strict, never asked, shifted by a row). **Partly superseded in review round 7 (section 19.2): the three pre-tests did not make the rules linear (the reviewer's text held the thing they look for, and six more rules were quadratic); the rules are now linear by themselves and the pre-tests stay only as a cheap first test.**

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
6. Observation, **not changed**: the work of one redaction call is bounded by 20000 values (`LIMITS.nodes`) of at most 20000 characters (`LIMITS.scanBound`) each, so a hostile entity could still make one rebuild read up to 400 million characters (80 million before this round); there is no total-character budget per entity. The 5000-entity budgets are green, the shapes that made single texts quadratic are closed (class 7), and a total budget (which would replace the later values of one entity with `[more values omitted]`) is a small follow-up if the owner wants hostile attribute data bounded as well. **Superseded in review round 7: section 19.3 gives every entity a scan budget, because the seventh review showed that the work of one entity could be 38 seconds, which is not a bound at all.**
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

## 19. Review round 7 (15 Nov 2026): findings and fixes

The seventh review found one MAJOR defect in the **shipped card** and two MAJOR holes in the test net, one MINOR and one NIT. The defect was introduced by round 6 itself: reading a string whole, up to 20000 characters instead of 4000 (section 18.6), made some of the value rules
quadratic on a text that only *looks like* the start of a match, so that one entity with 200 attributes of such a text (a space, `.local`, an at sign, then `0123.` repeated, 19990 characters) kept the main thread busy for **37,941 ms** on every update of that entity (round 5: 1,506 ms), and with it
the alert strip. The round-6 tests named three texts and passed. The direction of this round was the one of round 6, applied to speed: **close the class, not the instance**. Each finding was reproduced first, against the committed round-6 tree (section 19.9), then closed by tests that fail
without the fix (the new suites fail on the round-6 card: 17 tests of `scan`, `static`, `element` and `real-catalogue`, and 6 of the 8 of `perf`; the new Python checks fail on the round-6 patterns: 9 of them), and by mutants that undo each fix. Nothing pinned, sealed or deployed was edited, nothing is
live, nothing was pushed, and no assertion was weakened or deleted (section 19.10).

### 19.1 The findings and what was done

| # | Severity | Finding | Fix | Proof |
|---|---|---|---|---|
| 1 | MAJOR | The performance class. `redactString` reads up to 20000 characters; the dotted MAC look-ahead, the e-mail rule and the private host name rule are quadratic on near-miss text; the probe took 37,941 ms for 200 attributes. The 5000-entity budgets use benign data and missed it | **Every rule is bounded** (section 19.2) and **an entity has a scan budget** (section 19.3: 100000 characters across its state, attributes and key names; the rest is withheld, not read). The generic search for more found six more: of the 23 rules, **nine** were not linear on the family of near-miss texts in round 6 (the reviewer's three, and the pass pair, the internal host name, the JWT, the url credentials, the connection pairs and the webhook rules; a text of `a.a.a.` took 75 ms at 20000 characters and 1,250 ms at 80000 in the url credentials rule) | `test/perf.test.mjs` (8 tests: every one of the 23 rules ALONE, with no gate and no pre-test, on 125 near-miss texts of 10000, 20000 and (where measurable) 80000 characters; the whole read; the reviewer's probe; four hostile entity shapes; the cost of the worst shape per character), `test/scan.test.mjs` (the differential test against the round-6 patterns, the budget), `static.test.mjs` (the count of unbounded quantifiers of every rule is pinned), the Python privacy suite (the scanners bounded and timed on the same texts); 23 mutants (14 of them `perf: true`, the ones about speed) |
| 2 | MAJOR | Mutants N31, N32 and N33 (a chunked read inside `valueReason`: chunks of 3000, 1024 and 4000 characters that overlap by 200, 128 and 400) survived all six node suites: every sweep kind is short (74 characters at most), so any overlap longer than the longest kind passes; the static pin froze the one line of `redactString` and not `valueReason` | **Long kinds**, secrets that only one rule recognises and only whole (a URL with a user name and a password of 150, 300, 600, 1200 and 3000 characters, and a connection pair with a value of 400 and 3000), swept at a stride below their length in carriers of 4500, 12000 and 20000 characters (6,045 cases), on the core, every door of the core and the row paths. And **every function on the redaction path is read** (section 19.5): the only calls that cut or split text, and the only loop that steps by more than one, are the documented ones, by function and by count | `scan.test.mjs` (4 tests), `static.test.mjs` (2 tests, the second with 8 planted cuts); 14 mutants (N30 to N33, the substring forms of the round-6 chunk mutants N02b, N03b, N09b and N29, four more windows, a cut in `redactNode` and in `keyInfo`). Against the round-6 suites N31, N32 and N33 SURVIVED (reproduced); against these all are killed |
| 3 | MAJOR | Mutant N13 (`keyHasFragment(String(key), extra)`, with no fold) survived: the catalogue fragment `site_owner` did not withhold `site_` plus a zero-width space plus `owner`, `site_` plus a Cyrillic o plus `wner`, or a fullwidth s plus `ite_owner` | **The key-fold class** (section 19.6): the matrix of 32 forms of one key (case, zero-width and bidi characters, soft hyphen, byte order mark, Cyrillic and Greek look-alikes, fullwidth letters, hyphen, space, dot, camel case, wrapped in other words) is withheld in the raw attributes, a row, the search index and both exports, and, in the DOM, in every row, open list, raw view, search, copy and download; and two fragments that no word join can find (`siteo` across a camel-case boundary and a zero-width space; `x__y` against a Cyrillic y) are found only by the fold itself, so the fold is what is tested | `scan.test.mjs` (3 tests), `element.test.mjs` (1 test); 5 mutants (N13, the words of a key made without the fold, the word join dropped, joined with nothing, joined with a space) |
| 4 | MINOR | Mutant N21 (`ui.strip.animate([{opacity:0},{opacity:0}], {duration:1e9, fill:'forwards'})` in Geek Mode, guarded by `typeof animate`) survived all six suites: minidom has no `animate` and no static rule refused it; only `check-strip --require` failed it (3168 of 3192) | **The dynamic-style class** (section 19.7): the Web Animations API (`animate`, `getAnimations`, `KeyframeEffect`, `Animation`, `computedStyleMap`, `commitStyles`, the timelines) and every dynamic stylesheet API (`adoptedStyleSheets`, `CSSStyleSheet`, `insertRule`, `deleteRule`, `addRule`, `replaceSync`, `registerProperty`, `paintWorklet`, `.sheet`, a `style` or `link` element made from code, `CSS.`, `getComputedStyle`, `matchMedia`, the animation events) are refused by a static rule, with 19 planted forms as negative controls. N21 is marked `browser: true` | `static.test.mjs` (2 tests); 8 mutants (N21 and seven more forms), N21 also handed to the headless check |
| 5 | NIT | `site_owner` withheld `site_owner` and `SITE_OWNER` but not `site-owner` or `siteOwner` | A fragment is also looked for in the key's words joined by an underscore (section 19.6) | `scan.test.mjs` (the NIT test: 10 forms and 3 controls), the matrix above; the same word-join mutants; the README says so |

### 19.2 The freeze, and how every rule is bounded now

> **Superseded in part by section 20.2 (review round 8):** six of these bounds (the JWT segments, the key block label, the URL token names, the connection pair value, the webhook host and the dotted MAC letter) lost matches that round 6 made, and are gone: those six rules are exact and linear without them. The rest of this section stands.

**What it was.** A value rule is a regular expression tried from every start position of the text. A start costs as much as the longest partial match from it, so a rule is quadratic when many starts can each walk a long run: `[a-z0-9._%+-]+@` from every word boundary of a long local part, `(?=[0-9a-f.]*[a-f])`
(a look-ahead to the end of a dotted text) from every start, `\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.local` from every start of a dotted text, and, found by the generic search of this round (six more rules, measured on the round-6 card: 195 ms for the dotted MAC rule, 191 for the host name, 170 for the e-mail, 154 for the pass pair, 94 for the internal host name, 85 for the JWT, 82 for url credentials, 66 for connection pairs, 28 for the webhook, each on one text of 20000 characters), a scheme read as a run (`\b[a-z][a-z0-9+.-]*://`), a connection pair's value,
a webhook host, a JWT's segments and the prefix of segments of an unquoted `pass=`. The names of the url token rule were bounded too, as a precaution (the family did not find that rule slow). Round 6 had already added three pre-tests, one per rule the reviewer named; the pre-tests only help when the text does not hold the thing they look for, and the reviewer's text did. The rules themselves are linear now. The pre-tests are kept (a cheap first test, pinned in
`static.test.mjs`), but nothing depends on them.

| Rule | What walked | Round-7 form | Verdicts |
|---|---|---|---|
| jwt | `[\w-]{4,}` from every `eyJ` (`eyJ-eyJ-eyJ-`...) | segments of 4 to 512 and 4 to 4096 characters; the tail after the second dot is unbounded (it follows a complete match) | the same up to those lengths; a longer JWT is still withheld by the long-encoded-value rule (a test) |
| key block | linear already | a label of 1 to 64 characters | the same |
| url credentials | the scheme as a run from every word boundary (75 ms at 20000 characters for `a.a.a.`, x15 for four times the length) | one scheme character before `://`; the user-info that follows is read once | a **superset**: also a scheme that starts with a digit, a plus, a dot or a hyphen |
| url token | parameter names of any length either side of the key word | at most 64 characters either side | the same up to 64 |
| connection pairs | the value (`[^;\s]+`) from every key word (`host=host=host=`...) | two forms: a value of 1 to 256 characters after any boundary; or a value of any length when the key stands at the start of the text or after a semicolon or a space (so no start lies inside the value of another) | the same for a value up to 256; a longer one only after one of those three boundaries |
| pass pair | a prefix of segments (`(?:[a-z0-9]+[_-])*`) from every start | none: a prefix such as `wifi_` ends at a separator, so the key word is always preceded by a character that is not a letter or digit, and that alone is the test | **exactly** the same (131 matches of the round-6 rule in the node differential test and 3,538 in the Python one: none lost, none gained) |
| e-mail | the local part as a run from every word boundary | starts at the at sign, with one local-part character before it | a **superset**: a local part with no word character (one made of dots and hyphens only) |
| MAC, dotted | the look-ahead for a letter ran to the end of the dotted text from every start | `{0,13}`: the letter must be among the fourteen characters of the address | **narrower, on purpose**: `2026.1114.0900.beef` is no longer read as an address because of the letters after it (the old rule also withheld `1234.5678.9012.abc`). The differential test lists what was lost: only texts whose every address is all digits |
| webhook path | the host (`[a-z0-9.-]+`) from every `hooks.` | 1 to 253 characters (the DNS limit) | the same up to 253 |
| internal host name | the scheme as a run | one scheme character | a **superset** (as url credentials) |
| private host name | the chain of labels from every word boundary | starts at the dot before the suffix, with one host-name character before it | a **superset**: `my_nas.local` is now withheld (the underscore broke the round-6 boundary) |

The other twelve rules have no unbounded quantifier that more than one start can walk (a run that the start itself is not a member of, a tail after a complete match, a fixed count): `static.test.mjs` pins the number of unbounded quantifiers of **every** rule, so a bound taken off or a rule written back as it was
changes a count and fails, in addition to the timing. **No verdict is lost to a bound** except the one named above: `scan.test.mjs` runs both forms of eleven rules on 8,000 short texts each, built from the rule's own words and near misses (between 131 and 3,959 of them matched by the round-6 rule), and asserts that
everything the round-6 rule matched is matched now, that the six rewrites that claim to be exact gain nothing, and, for the four supersets, prints what they gain (`.://` followed by an at sign, `-.lan`, `_1a.lan`: junk, never prose); a separate test pins what each bound does beyond its limit.

**A key is read once.** A list of 200 items under one 20000-character key re-read the key for every item (`isSecretKey` is a tokeniser, a fold and a search of 165 windows against every fragment). The verdict on a key is made once per call and remembered (a key the budget could not pay for is not remembered).

### 19.3 The scan budget

`LIMITS.entityChars` = **100000**. A budget is a plain object `{ left }`. Reading a string costs its length (a string past `LIMITS.scanBound` is withheld by its length and costs nothing); reading a key name costs its length (at most the bound), and the scan of a key name for secrets costs up to 200 more. What is read after the budget
is spent is **not read**: a string is withheld, a key is shown as `[withheld key N]` with its value withheld. The budget is one per entity: `partsFor` makes one and the entity's attributes, state, unit and name all draw on it. An export gives each row a budget of its own (`eachItem`), because the second pass reads what the
first pass kept, row by row. A person sees the same marker as for any withheld value (its tooltip already says "or it is too long to be checked") and, in the attribute list, one more line: **values not read** with the number of characters the budget pays for.

**Why 100000.** The largest real Intelligence entity, from the live shape listing, is 3,927 characters of names and encoded values: the budget is 25 times that (a test asserts at least 20 times, and that all sixteen entities together are a fraction of it, each having a budget of its own), so no honest entity is touched (a test reads every
Intelligence fixture with the budget at a hundred times and asserts the same output; none carries the note). The worst shape found by the generic search costs 0.25 microseconds per character (a JWT-like text), so a whole budget of the worst shape is about 25 ms on this PC, and the reviewer's probe (200 attributes of 19990 characters) is 5 texts read and
195 withheld: **3 ms**, from 37,941. The budget is also five of the longest strings the card reads (20000), so a harmless long text still has room.

**What it does not bound.** The cost of *many* hostile entities (a thousand entities each at the budget is a thousand times 25 ms); a total budget per snapshot would change what a person sees in a way that depends on the order of the entities, and was not done. Entity ids are read unbudgeted, up to the bound (a Home Assistant id is at most 255 characters, so this is a 20000-character
id that Home Assistant would not have made).

### 19.4 The performance net, and what it cannot see

`test/perf.test.mjs` (not part of the mutation runner's default suites: only the mutants about speed and the baseline are given it, because it takes about fifteen seconds). It runs **every rule alone** (the pattern, with no gate and no pre-test: the worst case, a text that opens every gate) on **125 near-miss texts**: each is a *unit* repeated
to the length asked, and a unit is the start of a match of some rule that never completes, a boundary character every dotted or segmented rule walks, or a mix (`a.`, `a-`, `eyJ-`, `a://u`, `host=`, `;host=`, `"a_pass"`, `hooks.a.b/`, `x.local`, `aabb.ccdd.`, `a.b.c@d:/x=pass 0123.4567.89ab `, the reviewer's own ` .local @ x `, ...). For each rule and text it asserts an **absolute bound** (60 ms at 20000
characters; the slowest measured is 4.9 ms) **and linear growth** (the time at 20000 divided by the time at 10000 is at most 3.5: linear is 2, quadratic 4 and more; the minimum of several runs, a very fast call repeated until the timer cannot hide how it grows, and looked at again with more trials before a failure is reported), so a quadratic rule fails on a fast or a slow machine alike. A second test repeats the check from 20000 to 80000
characters for every (rule, text) that takes measurable time (a pattern is not bounded by the scan bound, so a quadratic one shows there at 16 times). A third runs **the whole read** (an opener that passes every gate and every pre-test, then the unit) bare and under a key. Then the whole entity: the reviewer's probe, five hostile shapes (a text of every unit as an attribute, a list of 200 items under one 20000-character key, 200 keys of 20000 characters, a dict of 5000 short
near-miss strings, 20 hostile entities through a snapshot and both exports), and the cost per character of the worst shape.

**What it cannot see.** A rule that is quadratic only on a shape that none of the 125 units builds; the structural pin (the number of unbounded quantifiers of every rule) is the second net for that, and the differential test the third for the verdicts. The tests measure this PC and a generous multiple of it; on a machine ten times slower the bounds still hold, and the growth test does not depend on speed.

The Python scanners of `tools/tests/test_geek_mode_privacy.py` had the same shapes (the pass pair, the e-mail, the webhook, the JWT and the URL-with-user-info scanners: 1,130 ms for `a-` at 20000 characters); they are bounded the same way and **timed on near-miss texts** (block [7]: 21 scanners on 49 units, an absolute bound of 400 ms and a growth bound of 3.5, a negative control that the check sees the round-6 pass pair and e-mail
scanners, a differential test of the six changed scanners against their round-6 forms on 6,000 short texts each, and the three numbers the card and the scanners share: the dotted-MAC look-ahead, the JWT segments and the budget). `PASS_PAIR` and `WEBHOOK_PATH` still equal the card's rule text, which the suite checks (the pass pair of the card changed with it).

### 19.5 The chunk class, and every function on the redaction path

**The long kinds.** `test/secrets.mjs` gains seven kinds, each recognised by **exactly one rule, and only whole**: a URL with a user name and a password of 150, 300, 600, 1200 and 3000 characters, and a connection pair (`Server=` ... `;`) with a value of 400 and of 3000. The password is `Ab1!` repeated and ends in `!` (no run of letters or digits longer than three, so no
hex, base64 or word rule sees a part; the last character is not a local-part character, so the end of the URL is not an e-mail address). A test asserts, for each kind, that the one rule recognises it, that no head or tail of it is withheld on its own (apart from a head that already holds the whole user-info and the at sign), and that the stride of the sweep (a twelfth of the kind's length, at least 7) is below the width of the window a chunked reader could leave a secret of that length straddling.
The sweep puts each kind at that stride, and at the last four starts that fit, in carriers of 4500, 12000 and 20000 characters (6,045 cases): through `redactValue` bare, and through every door of the core (no key, a dict value, a list item, an attribute object, a revision key, with the fragments) (892 cases at a seventh of the starts), and through the row paths (the attribute and the state, the redacted raw attributes, the search text, both exports; 103 cases, 206 entities). Reviewer mutants N31, N32 and N33 (and 11 more windows) are
killed. A chunked reader with an overlap of 2,500 characters (shorter than the longest kind, 3,033) is killed by the 3000-character kind.

**The structure.** A sweep proves the rules are applied to every character; it cannot prove that no function **between** the string and the rules shortens it. `static.test.mjs` reads the 14 functions of the redaction path (`cleanText`, `fold`, `keyTokens`, `compileExtra`, `keyHasFragment`, `isSecretKey`, `valueReason`, `newScan`, `redactString`, `keyInfo`, `redactNode`, `newCtx`, `redactValue`, `redactAttributes`) and asserts that the only calls
that cut or split text are: the display cut in `cleanText` and in `redactString` (after the read), the tokeniser's split in `keyTokens`, the fragment count in `compileExtra`, the one overlapping key window in `keyHasFragment` (overlapping by one less than the longest fragment) and the 200-character key-name scan in `redactNode` (the name is shown cut at 120); that `valueReason` has one `match`, of the whole text, and never reassigns the text; that the only loop of the path that steps by more than one is the key window;
and that there is no `lastIndex`, `exec`, sticky flag or `subarray`. Eight cuts planted in `valueReason` (three forms), `isSecretKey`, `keyInfo`, `redactString`, `redactNode` and `keyTokens` are each seen. The pre-test table and the loop lines of `valueReason` are pinned too, so the four round-6 mutants about pre-tests stay killed (by this pin, since the rules no longer need them); and the wiring of the budget (where it is charged, that a key it cannot pay for is not read or remembered, that an export resets it per row).

### 19.6 The key-fold class (N13) and the key words (the NIT)

A catalogue fragment is now looked for in **two** haystacks: the key as written, folded (invisible and zero-width characters removed, compatibility forms folded, Cyrillic and Greek look-alikes turned into Latin) and lower-cased, as before; and the key's **words** (`keyTokens`: folded, split at a camel-case boundary and at every character that is not a letter or digit, lower-cased) joined by an underscore. So the fragment `site_owner` withholds
`site_owner`, `SITE_OWNER`, `site-owner`, `site owner`, `siteOwner`, `site.owner`, `site__owner` and `mySiteOwnerName`, and every one of them with a zero-width character, a bidirectional control, a soft hyphen, a byte order mark, a Cyrillic or Greek look-alike or fullwidth letters in it. It does **not** withhold `siteowner` (one word has no underscore to find; write the fragment `siteowner` for that), and a fragment is still a part of a key (`site_owner` is
a part of `site_owners`). The two haystacks differ on purpose, and the tests use it: the fragment `siteo` is found in `site` plus a zero-width space plus `Owner` only through the first (the words join to `site_owner`), and `x__y` in `x__` plus a Cyrillic y only through the first (the words join to `x_y`), so a break that drops the fold from the first haystack (N13) shows a value in those two cases, whatever the second does. The matrix test has a control: the same 32 keys with no fragment show every value.

### 19.7 The dynamic-style class (N21)

The round-5 and round-6 static nets refuse every way of writing an inline style, an attribute, a shadow root or a stylesheet that they knew. The Web Animations API was none of them: an animation with `fill: 'forwards'` hides an element without a style, an attribute or a rule, and no node DOM has `animate`. The static rule is now a list of APIs, not of spellings: `.animate(`, `getAnimations`, `KeyframeEffect`, `AnimationEffect`, `new Animation`,
the timelines, `computedStyleMap`, `commitStyles`, `.timeline`; `adoptedStyleSheets`, `CSSStyleSheet`, `CSSStyleDeclaration`, `insertRule`, `deleteRule`, `addRule`, `removeRule`, `replaceSync`, `registerProperty`, `paintWorklet`, `Worklet`, `styleSheets`, `cssRules`, `.sheet`, a `style` or `link` element made from code (the card's one `<style>` is made by the builder, by name, once), `style map`, `getComputedStyle`, `CSS.`, `animationend`, `transitionend`
and `matchMedia`. The real source passes them; 19 planted forms are each refused. N21 and seven more forms (`getAnimations`, `KeyframeEffect`, an adopted constructed stylesheet, `insertRule`, a second `<style>`, a `<link>`, `computedStyleMap`) are killed by the node suites; N21 is `browser: true`, so where Chrome or Edge is installed the mutation proof also hands it to the headless check, which fails it as before (the second opinion).

### 19.8 What the owner needs to know

1. **Nothing the owner has to do.** No pinned, sealed or deployed file was edited, and no integration step of section 8 changed. Production Mode is unchanged.
2. The shipped card changed in these places: the rules (section 19.2), the budget (section 19.3), the key verdict made once per key, the key words, and one attribute-list line when an entity is past its budget. `RULES` is **not** byte-identical to round 6 any more (11 of its 23 patterns changed): the privacy suite compares the card's text with the Python scanners' for the webhook path, the pass pair, the Wi-Fi text and the spaced MAC address, and the first two were changed in step.
3. **Observation, a limit of the bounds (withdrawn by section 20.9, observation 7: none of these limits exists any more):** a connection pair whose value is longer than 256 characters is matched only when its key stands at the start of the text or after a semicolon or a space; a JWT whose first segment is longer than 512 characters or second longer than 4096 is not matched by the JWT rule (it is withheld as a long encoded value); a parameter name of more than 64 characters either side of a key word is not seen by the url token rule; a host name of
   more than 253 characters in a chat webhook is not matched. None of these is a text a real source writes, and each is a number in one place of the source and one of `static.test.mjs`.
4. **Observation (the narrowing is withdrawn by section 20.9, observation 7):** the four superset rules withhold a little more than round 6 did (`1://nas`, `my_nas.local`, an address whose local part is only dots and hyphens); the one narrowing is the dotted MAC (`2026.1114.0900.beef` is shown, an all-digit dotted address is not distinguishable from a version number and is shown, as before).
5. **Observation, not changed:** many hostile entities; ids; see section 19.3. The one-entity worst case is now about 25 ms; the 5000-entity budgets are unchanged.
6. **Superseded:** section 18.7 observation 6 (no total-character budget per entity) is closed by section 19.3; the pre-tests of section 18.2 class 7 are kept but no longer needed.
7. The registry suite (`registry/tests`) was not re-run in this round: it reads nothing this change touches (as in round 6).

### 19.9 Results of the runs

| Run | Result |
|---|---|
| `node --test test/*.test.mjs` (core 157, element 120, coverage 4, static 54, real-catalogue 159, strip-check 11, scan 16, perf 8, mutation proof 367) | 896 of 896 pass in 534 s (round 6: 809 in 404 s; the nine extra minutes of the mutation proof are 50 more mutants and one more suite per mutant); **357 of 357 mutants are killed by the node suites alone** (the 307 of round 6 and 50 new: 23 about speed and the budget, 14 about a chunked read, 5 about the key fold, 8 about the Web Animations API and the stylesheet APIs); the mutation proof also hands seven of them (J13, J14, J20, J21, AR08, P07 and N21) to the headless check on this PC and all seven fail it |
| the reviewer's five survivors N13, N21, N31, N32, N33, run against the round-6 suites (the committed tree) | all five SURVIVED, as reported; against these suites all five are KILLED (and so are the 45 other new mutants) |
| the reviewer's probes against the round-6 card | `probe-perf7c`: one 19990-character text 191 ms, 200 of them in one entity **37,906 ms**; `probe-overlap7`: N31 (a 300-character password at 2790), N32 (200 at 890) and N33 (500 at 3590) SHOW the password, the real card withholds it; `probe-r7`: N13 shows the value under `site_`, a zero-width space, `owner`, under a Cyrillic o and under a fullwidth s, and the real card shows the hyphen form (the NIT) |
| the same probes against this card | the 200-attribute entity: **3 ms** (5 texts read, 195 withheld); the three straddling passwords withheld; every form withheld, the hyphen form too |
| the new suites run against the round-6 card (`ECCO_MODE_SHELL_PATH` at a copy of it, with only the table hook added) | 17 tests of `scan`, `static`, `element` and `real-catalogue` FAIL there (the budget, the key fold, the bounds and the structure tests: they describe what round 6 did not have) and 6 of the 8 tests of `perf` fail (its slowest rule on a near-miss text: 195 ms at 20000 characters; a snapshot of 20 hostile entities: 6.5 s); the new Python block fails 9 checks against the round-6 patterns |
| the nine rules of round 6 that are not linear on the 125 texts (measured on the round-6 card, one text of 20000 characters) | dotted MAC 195 ms, private host name 191, e-mail 170, pass pair 154, internal host name 94, JWT 85, url credentials 82, connection pairs 66, webhook path 28; none is above 5 ms now (the slowest is the JWT on `eyJ-` repeated, 4.8 ms) |
| `node preview/check-strip.mjs --require`, `--selftest` | PASS: 3192 of 3192 checks (unchanged: the strip, its places and attributes are as before); SELFTEST PASS: the card passes and 31 of 31 broken copies fail. N21 (the animation) against the headless check: FAIL, 3168 of 3192 hold, as the reviewer reported |
| `tools/tests/test_geek_mode_{catalogue,coverage,ledger,fixtures,privacy,example}.py` | all pass (134, 219, 68, 102, 180 and 35 checks; privacy gained 31, 3 s) |
| `frontend/ecco-mode-shell/test/test_example_dashboard.py` | all example-dashboard checks pass |
| `tools/geek_mode_coverage.py --check`, `tools/gen_geek_fixtures.py --check` | both match a fresh regeneration (nothing the tools read or write changed) |
| `tools/validate_repo.py` | PASSED, with no edit to any pinned file (no demand for a manifest entry, a changelog line or a chain entry arose) |
| `tools/run_offline_tests.py --root tools/tests` | 21 of 21 pass (201 s), including the repository's public privacy scan over the new files; the other roots (`ecco_core`, `health`, `intelligence`, `home-assistant`) read nothing this change touches and were not re-run; `registry/tests` neither (section 19.8, observation 7) |
| measured, this PC | the slowest rule alone on any of the 125 texts: 4.8 ms for 20000 characters (round 6: 195 ms); the whole read of the worst text: 5.1 ms; the worst shape costs 0.26 microseconds per character, so a whole budget of 100000 characters is about 26 ms; a snapshot of 2000 entities with a harmless 4500-character text each: 188 ms (round 6: 241 ms); the 5000-entity budgets of AC12 are green; the Python scanners: from 1,130 ms (the pass pair on `a-` at 20000 characters) to under 5 ms |

### 19.10 Changes to existing tests and files (none weakens an assertion)

- `ecco-mode-shell.js`: 11 of the 23 patterns of `RULES` were bounded or rewritten (section 19.2; the gates are as they were); `LIMITS.entityChars` was added; `newScan`, `keyInfo` and `KEY_UNREAD` were added; `redactString` takes a budget and a precomputed revision-key flag (its first two parameters and its use for entity ids are as before); `redactNode` asks `keyInfo` for the verdict on a key (once per key and call), charges the scan of a key name and shows a key the budget could not pay for
  as a withheld key; `newCtx` has a budget, a key table and `eachItem`; `isSecretKey` also looks for a fragment in the key's words; `partsFor` makes one budget per entity and adds the "values not read" line; `exportRows` gives each row a budget; `SCAN_RULES` (a table, a test hook) was exported. The stylesheet, the strip, the mode switch, the controller and every DOM builder are untouched, so **no pin and no fixture was regenerated** (`style.pin.json`,
  the generated catalogue, ledger, live shape and fixtures are byte-identical to round 6; `--check` of both tools passes).
- `core.test.mjs`: **not changed.** `element.test.mjs`: 3 tests appended. `static.test.mjs`: 7 tests appended, nothing existing changed. `real-catalogue.test.mjs`: 2 tests appended. `secrets.mjs`: the long kinds appended (the older lists are unchanged, so no older test sees them).
- New files: `test/perf.test.mjs` (8 tests), `test/scan.test.mjs` (16 tests) and `test/near-miss.mjs` (the 125 units).
- `mutations.test.mjs`: 50 mutants appended; `scan.test.mjs` was added to the suites every mutant runs, and `perf.test.mjs` to the baseline and to the mutants flagged `perf: true`. **Re-anchored: 6**, with the same intent: `AC10-pass-pair-colon-prose` (the unquoted alternative has no prefix of segments), `AC10-webhook-services-form-dropped` (the host is bounded), `AC10-extra-patterns-ignored` (the line it removes now also looks in the key's words), `AC10-export-not-reredacted` (the export line carries `eachItem`), `AC10-extra-patterns-not-prepared` (the options line carries the scan budget) and `AC10-mac-dotted-versions` (the look-ahead is bounded). The first run of the mutation proof said so itself: a mutant whose target text is not found is a failure, and these three were. **Retired: none.** The four pre-test mutants
  of round 6 (`AC12-r6-pretest-host-dropped`, `-mac-dropped`, `-pass-dropped`, `-never-consulted`) were about speed, which no longer depends on the pre-tests; they are kept and are now killed by the static pin of the pre-test table and of the loop that asks it (section 19.5).
- `tools/tests/test_geek_mode_privacy.py`: six scanner patterns were bounded (the e-mail, the JWT-like and the token-shape JWT, the URL with user-info, the webhook path, the dotted MAC, the pass pair; the webhook path and the pass pair stay equal to the card's rule text, which an existing check compares) and block [7] was appended (section 19.4). No existing check was changed. The other Python suites and tools are untouched.
- `README.md`: the budget, the bounded rules and the key words, the test table (three new files, the static round-7 row, the mutant count).
- Section 18.7 observation 6 and section 18.2 class 7 of this document carry a one-line note that round 7 supersedes them.

## 20. Review round 8 (15 Nov 2026): findings and fixes

The eighth review found **two MAJOR defects in the shipped card** and one MAJOR hole in the test net, two MINOR findings and one NIT. The first shipped defect is a **regression that round 7 itself introduced**: to make the value rules linear, round 7 bounded some of their quantifiers (`{0,64}`, `{1,256}`, `{4,512}`, `{1,64}`, `{1,253}`, `{0,13}`), and a bounded rule stops matching a secret whose *component* is longer than its bound. Five inputs that round 6 withheld were **shown** by the round-7 card, one of them a URL whose token parameter name is 65 characters long and whose value is a real secret (`?` plus 65 letters plus `_token=s3cr3tvalue`). The second is a freeze of the *first render*: the entity budget of round 7 bounded one entity and nothing bounded the sum, so 50 entities of hostile text took 982 ms, 200 took 3,912 ms and 5,000 took 112,856 ms. The third is a test gap: mutant M14 (an unread key is not treated as secret) survived all eight suites, so a number or a boolean under `password`, `pin_code` or `latitude` would have been shown once an entity's budget was used up. Each finding was reproduced first, against the committed round-7 tree (section 20.10), then closed **by class**, not by instance: the new tests fail on the round-7 card, and each fix has mutants that undo it. Nothing pinned, sealed or deployed was edited, nothing is live, nothing was pushed, and no assertion was weakened or deleted (section 20.11; the pins that were changed were changed from "shown" to "withheld", which is the direction the owner asked for, and each is listed).

### 20.1 The findings and what was done

| # | Severity | Finding | Fix | Proof |
|---|---|---|---|---|
| 1 | MAJOR (shipped) | **Bounded rules lose matches** (the regression class). The URL token, connection pairs, JWT, key block, webhook and dotted MAC rules stopped matching past their bounds; the reviewer's five inputs (token name of 65, `(uid=` plus 300, `x,host=` plus 300, a JWT first segment over 512 without a digit run, a key block label of 80) were withheld in round 6 and shown in round 7 | **FAIL CLOSED, by exactness** (section 20.2): every one of the six rules is rewritten so that it has no bound on any component and is still read once, whatever the text (a look-behind from the second dot, a look-behind from the semicolon, two look-aheads from the separator, a look-behind from `/services/`, the last letter of a run, and the round-6 key block, which is linear as it stands). They match exactly what the round-6 rules matched (the dotted MAC too: `2026.1114.0900.beef` is withheld again). Anything that still has a limit (a string over 20000 characters, an entity over its budget, a snapshot over its budget, a key name over 20000 characters) is **withheld whole**, never shown in part | `test/differential.test.mjs` (5 tests, 58,382 generated texts, the whole read and rule by rule, with the round-7 forms as negative controls), `test/scan.test.mjs` (the bounds test, 8 pins flipped from shown to withheld), `tools/tests/test_geek_mode_privacy.py` block [8]; 15 mutants (the round-7 forms and the round-6 forms of each rule) |
| 2 | MAJOR (shipped) | **The first snapshot has no total budget.** `LIMITS.entityChars` bounds one entity; 50 discovered entities of near-miss text (five attributes of 19999 characters each) took 982 ms, 200 took 3,912 ms, 5,000 took 112,856 ms; only the first render freezes the strip (updating one entity stays at 25 ms) | **A snapshot budget** (section 20.4): `LIMITS.snapshotChars` = 2,000,000 characters across all entities, charged in a documented order (alert-bearing, headline, other sources, discovered by id); past it every remaining entity is **not read**: its row says so, its values are withheld and nothing of it is scanned, shown, searched or exported. Alerts read the raw states and are never affected | `test/budget.test.mjs` (14 tests), `test/perf.test.mjs` (3 tests: 16 families x 50, 200 and 5000 entities, the worst first snapshot is **60 ms**), `test/static.test.mjs` (the wiring), `test/element.test.mjs` (the DOM); 22 mutants |
| 3 | MAJOR (test gap) | **M14.** `KEY_UNREAD = { secret: false }` survived all eight suites: after the budget was used up, every number and boolean under an unread key (`pin_code: 734921`, `password: 123456`, `latitude: 51.50722`, `wifi_pass: true`) was shown under a withheld key name | Tests of every path (section 20.5): raw attributes, rows, attribute rows, search index, a search, JSON and CSV export, for a number, a boolean, a list and a nested dict, with the controls that show it is the budget and not the names | `test/budget.test.mjs` (3 tests); M14 and a strings-only variant are killed |
| 4 | MINOR (test gap) | **Mutants M38 and M40b** (the animation API reached by a name built from pieces, and by walking the prototype chain) survived all eight suites; `check-strip --require` failed them, but only where Chrome or Edge exists | **Behavioural tripwires** (section 20.7): every element, shadow root, fragment and document of the DOM stand-in has `animate`, `getAnimations`, `attributeStyleMap`, `computedStyleMap`, `sheet`, `adoptedStyleSheets`, `insertRule`, `deleteRule`, `addRule` and `replaceSync` on its prototype, and each records being read or called; the element tests assert **zero** after every test and step by step in both modes. **Static rules** refuse a computed member access with a non-literal key unless it is on the pinned list, the prototype chain, descriptors and `for ... in`, and any string that is the name of a tripwire | `test/element.test.mjs` (2 tests and the `afterEach`), `test/static.test.mjs` (5 tests), `test/minidom.mjs`, `test/member-guard.mjs`; 8 mutants (M38, M39, M40, M40b and four more ways to reach the members), killed by the element suite alone |
| 5 | MINOR (shipped) | **Charge order.** `partsFor` read the attributes first, then the state, the unit and the name: one entity with six attributes of 19990 characters and the state `healthy` showed the state as `[withheld]`, no unit and no name | The state, the name and the unit are charged and read **first**, then the attributes (section 20.6) | `test/budget.test.mjs` (2 tests), `test/scan.test.mjs`, `test/static.test.mjs` (the order, by the source); 2 mutants |
| 6 | NIT | The Python e-mail scanner missed an address of 17 or more labels that all hold a digit (and a label of 64 characters), which the round-6 form found | The domain has no bound (the local part keeps its 64, which loses nothing) and the **differential property is mirrored** in the Python scanners (section 20.8): five more scanners were bounded by round 7 and are exact again | `tools/tests/test_geek_mode_privacy.py` block [8] (195 checks in all) |

### 20.2 The regression, and the rule: fail closed, or be exact

**What happened.** A value rule is a regular expression tried from every start position. Round 7 made each rule linear by bounding the component that a long run could make it walk again, and chose bounds no real source reaches (a name of 64, a value of 256, a label of 64, a host of 253). But a bound is also a place where the rule *stops looking*: a secret whose component is longer is matched by no rule and, if no other rule reads it, is shown. The round-7 tests pinned those bounds as limits ("beyond this the text is not matched") and the differential test of round 7 used short texts, so it could not see them.

**The rule of this round.** A rule that cannot read a text exactly must **not show it**. There are two ways to hold that: write the rule so that it is exact *and* linear (preferred: it loses nothing and withholds nothing it should not), or, where a limit remains, withhold the whole string. The six rules that had a bound are now exact; the limits that remain are all of the second kind and none lets a part of a secret through:

| Limit that remains | What happens beyond it |
|---|---|
| a string over `LIMITS.scanBound` (20000 characters), a key name over it | withheld whole (not read in part) |
| an entity over `LIMITS.entityChars` (100000 characters read) | the rest of that entity is withheld, and says "values not read" |
| a snapshot over `LIMITS.snapshotChars` (2,000,000) | the rest of the entities are not read; their values are withheld |
| a dict over 200 keys, a list over 200 items, depth 8, 20000 values | the rest is dropped, with a count, never shown |
| a key name read after the entity budget is gone | an unread key, and every value under it withheld whatever its type (section 20.5) |

**How each rule is exact and linear.** The device is the same in each: choose the start so that only one start is possible per run, and read the rest of the secret *behind* or *ahead of* it in a look-behind or look-ahead that stops at the first character that cannot belong to it.

| Rule | Round 6 (exact, quadratic) | Round 7 (linear, lost matches) | Round 8 (exact and linear) |
|---|---|---|---|
| `jwt` | `\beyJ[\w-]{4,}\.[\w-]{4,}\.[\w-]*` (quadratic on `eyJ-eyJ-eyJ-`) | `{4,512}` and `{4,4096}` | `(?<=\beyJ[\w-]{4,}\.[\w-]{4,})\.`: the match is the second dot, the two segments and the `eyJ` are read once behind it; a text with no dot is not read at all |
| `key block` | `-----BEGIN [A-Z0-9 ]+-----` | `{1,64}` | the round-6 form: the label holds no hyphen, so no other start lies inside it, and it was never quadratic |
| `url token` | `[?&#;][\w.%-]*(?:KEYWORD)[\w.%-]*=[^&\s]{3,}` (quadratic on `?tokentoken`) | `{0,64}` either side | `[?&#;](?=[\w.%-]*=[^&\s]{3})(?=[\w.%-]*?(?:KEYWORD))`: one start per separator; two look-aheads read the name once each |
| `connection pairs` | `\b(?:KEY)\s*=\s*[^;\s]+\s*;` (quadratic on `host=host=host=`) | a value of 256 after any boundary, any length only after a space or a semicolon | `(?<=\b(?:KEY)\s*=\s*[^;\s]+\s*);`: the match is the semicolon, and the pair is read once behind it |
| `webhook path` | `hooks\.[a-z0-9.-]+/services/...` (quadratic on `hooks.hooks.`) | `{1,253}` | `(?<=hooks\.[a-z0-9.-]+)/services/...`: read once behind `/services/` |
| `MAC address (dotted)` | `\b(?=[0-9a-f.]*[a-f])4.4.4\b` (the look-ahead ran to the end from every start) | the letter must be in the 14 characters of the address | two alternatives, each read once: a letter inside the address (the 14-character window), or **the last letter of a run** (a lazy look-ahead stops at the next letter, so the run is read once over all its letters) with the address looked for behind it, once per run |

`2026.1114.0900.beef` is therefore **withheld again**, as in round 6 (round 7 showed it). It is a false positive in the safe direction (a dotted version text with a letter after it); an all-digit dotted address is, as before, indistinguishable from a version number and is shown.

**No generic marker backstop was added.** The reviewer suggested withholding a whole string when a component exceeds its bound near a secret marker. With every rule exact there is no component bound left to exceed, so the backstop would only add false positives (a long benign sentence that mentions `token` or `key`); the *differential gate* (section 20.3) is the guarantee instead, and it fails the day a rule gains a bound that loses a match.

### 20.3 The differential gate

`test/reference-r6.mjs` is the round-6 rule set **frozen** (extracted verbatim by a script from `git show f4e52be:frontend/ecco-mode-shell/ecco-mode-shell.js`: the fold, the 23 rules, the pre-tests, the three whole-text rules and `valueReason`). It is the yardstick, slow on near-miss text on purpose, and run only on the generated corpus. `test/differential.mjs` generates that corpus: **46 families** (41 swept, 5 that are one text in many places), one per kind of secret, each with ONE component whose length is swept at every value from 1 to 300 and then 400, 600 and 1000 (303 lengths in 4 places each), and at the lengths on either side of every bound a rule has had (63 to 66, 252 to 258, 511 to 514, 4095 to 4098, and a spread beyond; 42 lengths in carriers of 4000 characters, at the start, in the middle, at the end and glued with no space), with every seventh text carrying a zero-width character so that the fold is exercised too. The fillers are letters that no other rule can read (`g` to `z`), so a rule that lost a match cannot be hidden by another rule reading the filler.

The assertion is one direction only: **whatever the reference withholds, the card still withholds** (the card may withhold more, never less). It is made twice:

1. **the whole read** (`redactValue`, with a key, without one): 58,382 texts, the round-6 rules withhold 57,959 of them, the card withholds all of them;
2. **rule by rule** (the card's rule of the same name, with its gate and its pre-test): 25,727 texts, 26,037 matches of the reference, none lost, and each of the 23 rules is exercised. A rule that lost a match is named even where another rule would still withhold the text.

**The gate can see the class** (negative controls, in the same test file): the round-7 bounded forms of the six rules lose 1,446 (url token), 81 (connection pairs), 40 (jwt), 482 (key block), 148 (webhook path) and 624 (dotted MAC) of these texts. **Against the round-7 card** the whole-read test finds **4,771** texts that round 6 withheld and round 7 showed, and the rule-by-rule test finds **2,821** lost matches (section 20.10). The reviewer's five inputs are also named, one by one, in a test of their own, and are withheld with a key, without one, under a revision key and inside a list.

The same property is mirrored in the Python scanners (section 20.8). The exactness in the other direction (the new rule matches nothing the round-6 rule did not) is asserted for the six rules in `test/scan.test.mjs` (its `EXACT` list), on 8,000 short texts each.

### 20.4 The snapshot budget

**The class.** `LIMITS.entityChars` bounds one entity (round 7), and nothing bounded the sum over the entities of a snapshot: the first render of a view with many entities of near-miss text was not bounded. The same holds for the *shape* of the work (twenty thousand small values cost the entity budget nothing, because it counts characters).

**The budget.** `LIMITS.snapshotChars` = **2,000,000** "characters" across all the entities of **one snapshot**. An entity costs what it read (its characters, at most `entityChars`) plus `LIMITS.nodeChars` (1) for every value it visited, and **at least** `LIMITS.entityBaseChars` (250: its row, its attribute rows, its search text). The cost is kept with the entity's cached parts, so a row that is reused from the cache is charged what it cost when it was read, and **the same states always give the same snapshot** (a cached row can neither be shown for an entity that is now past the budget nor hide one that now has room). The id of an entity is read whether or not the entity is, at most 255 characters (`LIMITS.entityIdChars`, the Home Assistant limit): a longer one is not an entity id and is withheld unread, so the ids cost the snapshot nothing and are bounded by 255 characters each.

**Why 2,000,000.** Measured on the development PC: the worst of the 16 near-miss families costs **21 nanoseconds per unit**, so a whole budget is **42 ms** (the cost of the worst whole read in `perf.test.mjs` is 49 ns per character); ordinary text costs 10 to 12; a small entity about 13 microseconds (about 250 units). So a snapshot that has used the whole budget has taken well under 0.1 s here, and a phone five times slower stays under half a second. It is 65 times the real Intelligence view (16 entities; 30,000 characters in all), exactly twenty of the largest entities the entity budget allows, and **5,000 small ordinary entities fit with room to spare** (1.25 million). A smaller budget would have left the 5,000-entity scale tests (which are ordinary data) with unread entities; a larger one buys nothing.

**The order** (documented in the source and pinned by a test):

1. the entities an alert of the catalogue watches (what the owner must be told about is read first);
2. the catalogue's `headline` sources, in catalogue order;
3. the other sources, in catalogue order;
4. the discovered entities, in the order of their ids.

The decision is made *before* the cache is asked, from the budget as it stands: the first entity that finds the budget at zero or below, and every one after it, is **not read**.

**An entity that was not read** has a row like any other, with the status that its timestamp and its state word give (the card's own words `Unavailable` and `Unknown` are kept), `stateText` `[withheld]`, no unit, one attribute row that says "values not read: ...", a raw view that holds one marker (`[values not read]`), `problem: true` (the Problems filter lists it), `unread: true`, a cost of zero, and a count in the Geek header ("N not read (too much data for one pass)") and in the Production note ("N data points were not read: this view holds more data than it reads at once"). **Nothing of the entity is in the row**: no state, no attribute, no name, no marker text, in the row, the attribute list, the raw view, the search index, a search or either export (tested with a marker in every text of every entity, 30 entities of which about 10 were not read). Its attributes are not scanned and its parts are never built.

**Alerts are never hidden.** `deriveAlerts` works on `alertInputs`, which are built from the raw states with no budget in sight (a test pins that the budget is not mentioned after `const alertInputs`). Thirty alert-bearing entities in a state that raises an alert, ten of them not read, give all thirty alerts, the same ids as the same states made small. And an entity an alert watches is read **first**.

**What it does to the existing tests.** Six tests of rounds 5 to 7 built thousands of entities with texts of 4,500 to 20,000 characters in one snapshot (8 million characters or more) and expected every one to be read. They are now read in snapshots of 100 or 30 cases (the budget is not what they test), and each batch asserts that nothing was unread, so every assertion is still made on every case. The two that were about 2,000 entities of 4,500 characters now assert the new fact: 350 fit and are read whole; of 2,000, about 440 are read and the rest say so. Nothing was relaxed (section 20.11).

### 20.5 KEY UNREAD (M14)

After an entity's budget is used up, a key is not read: `keyInfo` returns `KEY_UNREAD`, which is `secret: true`, so **every value under it is withheld**, of whatever type. Round 7 had the code right and the tests only had strings under such keys. `test/budget.test.mjs` puts, after six harmless texts that use the budget, `pin_code` (a number), `password` (a number), `latitude` (51.50722), `wifi_pass` (a boolean), a list of numbers, a nested dict, and four keys with perfectly harmless names holding a number, a boolean, a list and a dict, and asserts they are withheld in the raw attributes, the row, the attribute rows (each says `withheld`), the search index, a search for each number, the JSON export and the CSV export. The controls show that the withholding is the budget's and not the names': with the budget not used up, the secret names are withheld by name and the harmless ones are shown whole. M14 (`secret: false`) and a variant that withholds only strings are killed.

### 20.6 Charge order

`partsFor` now reads the **state**, then the **name**, then the **unit**, and only then the attributes, all on the entity's one budget. An entity that is over its budget still shows its state, its name and its unit, honestly, and it is the attributes past the budget that are withheld (an unread key, and a "values not read" line). What the order does not change is what is withheld: a state, a name or a unit that looks like a token or a connection string is withheld wherever it is read (tested). The attributes `friendly_name` and `unit_of_measurement` are also attributes, and are read again (and charged again) in their place.

### 20.7 The tripwires and the member guard

**Class.** A member of an object is reached by something that is not its name: a name made of pieces (M38), a computed key held in a variable, the prototype chain (M40, M40b). The round-7 net refused the *name* of the animation and stylesheet APIs in the source, and the DOM stand-in had no such member, so the mutants' own `typeof` test was false and they did nothing.

**Behavioural net.** `test/minidom.mjs` arms every element, shadow root, fragment and document with `animate`, `getAnimations`, `computedStyleMap`, `insertRule`, `deleteRule`, `addRule`, `replaceSync`, `attributeStyleMap`, `sheet` and `adoptedStyleSheets`, as accessors on the prototype (as a browser has them). Reading one records it; calling the function it returns, or a method of the object it returns (a style map, a stylesheet), records that too. `document.recorded.apiCalls` is the record. `element.test.mjs` asserts the record is empty **after every test** (`afterEach`) and, in a test of its own, after each step of a session in both modes (mount, switch, open everything, search, filter, update, switch back and forth, disconnect). A second test is the negative control: each member is recorded on each kind of object, by name, by a name made of pieces, by a computed key and by walking the prototype chain. Against the card with M38, M40b, a computed-key `getAnimations` or M39 (the typed style map), the element suite alone fails: every test that mounts the card fails its `afterEach` with "a tripwire was touched".

**Static net.** `test/member-guard.mjs` reads the structure of the source (a one-pass scanner that blanks strings, templates and regular expressions, with a stack for `${}`). (1) The **53 computed member accesses** of the card whose key is not a literal are pinned by receiver and key; the only ones on a DOM object are the two buttons of the mode switch, by mode (`ui.opts[m]`, `this._ui.opts[next]`). A new one, or a changed receiver, is refused until a person decides it. Eleven planted forms are the negative controls (M38's form, a key made of a call, of a template, of `String.fromCharCode`, a bracket on the strip, the shell, the host, a root, a child and the document), and six forms that must *not* be seen (a literal key, an array literal, `for ... of` and `return` before a bracket, a regular expression, a template text) are the controls. (2) **The prototype chain is never touched** anywhere in the module: no `getPrototypeOf`, `setPrototypeOf`, `getOwnPropertyNames`, `getOwnPropertyDescriptor(s)`, `getOwnPropertySymbols`, `defineProperty`, `__proto__` as a property, `.constructor`, `.prototype`, `for ... in`, `Reflect`, `Symbol`; the one use of a prototype is the `hasOwn` helper, pinned to one place; fourteen planted forms. (3) **No string, template or bracket of the module is the name of a tripwire member** (`strip['animate']` is a door the name rules did not see).

**Limit (unchanged in kind).** A static read of source cannot exclude every dynamic way to reach a member; the card already forbids `eval`, `Function`, `Reflect`, `Proxy` and `globalThis`, and the tripwires look at the result. Where Chrome or Edge exists, M38, M40 and M40b are also handed to the headless check, as a second opinion.

### 20.8 The Python scanners

`tools/tests/test_geek_mode_privacy.py` (Python 3.11 or later: it now uses an atomic group and possessive quantifiers, which the CI's 3.12 has):

- **The NIT.** `EMAIL`'s domain has no bound; the local part keeps its 64 (a longer one still matches, from its last 64 characters, so nothing is lost). An address of 21 labels that all hold a digit, and one with a label of 64 characters, are found; the round-7 form found neither (a check says so).
- **The property, mirrored.** Round 7 also bounded the JWT scanner (512 and 4096), the JWT form of the token-shape scanner, the webhook scanner (253) and the dotted-MAC scanner (14 characters). Block [8] is the same differential gate: the families of seven scanners, each component swept from 1 to 1000 and at 4100 characters, bare and at the start, in the middle and at the end of prose (30,372 texts that the round-6 forms match), asserting that every text the round-6 form matched is still matched; and the round-7 forms of five of them lose texts on that corpus (negative controls: 4, 4, 528 and 56). The JWT forms and the webhook scanner are exact again by an **atomic group on the first `eyJ` (or `hooks.`) of a run and a possessive read of the rest**, from the start of a run: one start per run, every character read once. The dotted-MAC scanner needs no trick (it needs the address to stand alone, so its run ends at the address; the round-7 bound never changed one of its verdicts, and it is the round-6 form again).
- **The agreement with the card.** The webhook check of round 2 asserted that the card's pattern and this scanner's were the same text. They cannot be any more (the card writes the host as a look-behind from `/services/`, which Python's `re` cannot), so the check now asserts the same first alternative, the card's second alternative as the documented transformation of the round-6 form, and this scanner's second as the documented atomic form, and each is proved equal to the round-6 form by the differential checks (this block and `test/differential.test.mjs`). The other agreement checks (JWT, dotted MAC, the scan budgets) were updated for the new rules; the snapshot budget is checked too.

### 20.9 What the owner needs to know

1. **Nothing the owner has to do.** No pinned, sealed or deployed file was edited, and no integration step of section 8 changed. Production Mode is unchanged.
2. The shipped card changed in these places: six rules (section 20.2), `partsFor` (order, cost), `buildSnapshot` (the budget and the order), `buildRow` and `makeRow` (an entity that was not read), `redactValue` and `redactAttributes` (the count of values visited), `summarise` (one sentence) and one line of the Geek header. `RULES` differs from round 7 in 6 of its 23 patterns. The stylesheet, the strip, the mode switch, the controller and every other DOM builder are untouched, so **no pin and no fixture was regenerated** (`style.pin.json`, the generated catalogue, ledger, live shape and fixtures are byte-identical; `--check` of both tools passes).
3. **A visible change, only in a pathological view:** an entity past the snapshot budget is shown as "not read" (its id is still shown; its values are not). With the real Intelligence view (16 entities, 30,000 characters) nothing is unread; neither is anything with 5,000 small ordinary entities.
4. **Observation:** `2026.1114.0900.beef` and other dotted texts with a letter after the address are withheld again, as in round 6. An all-digit dotted text is shown.
5. **Observation:** `test_geek_mode_privacy.py` needs Python 3.11 or later (atomic groups); the repository's CI runs 3.12.
6. **Observation, not changed:** the snapshot budget bounds the *first render*; a stream of updates to many entities at once is bounded by the update pump of section 14 (eight at once, the rest coalesced), and each rebuild reads only the entities whose state objects changed, plus the cheap rows of the unread ones (about 5 microseconds each).
7. **Superseded:** section 19.8 observation 3 (the limits of the bounds: a connection pair over 256, a JWT segment over 512 or 4096, a parameter name over 64, a webhook host over 253) is withdrawn: none of those limits exists any more. Section 19.8 observation 4 (the one narrowing, the dotted MAC) is withdrawn too. Section 19.2's table of bounds is superseded by section 20.2 for the six rules.
8. The registry suite (`registry/tests`) was not re-run in this round: it reads nothing this change touches (as in rounds 6 and 7).

### 20.10 Results of the runs

| Run | Result |
|---|---|
| `node --test test/*.test.mjs` (core 157, element 123, coverage 4, static 59, real-catalogue 159, strip-check 11, scan 16, perf 11, budget 14, differential 5, mutation proof 415) | **974 of 974 pass** in 629 s (round 7: 896 in 534 s; the extra minutes of the mutation proof are 45 more mutants); **402 of 402 mutants are killed by the node suites alone** (the 357 of round 7, 4 retired, 49 new: 15 about the bounds and their round-6 forms, 26 about the unread key, the snapshot budget, the charge order and the DOM, and 8 about reaching the animation and stylesheet members by a name that is not written); the mutation proof also hands the nine browser-flagged mutants (the seven of round 7, M38 and M40b) to the headless check on this PC and all nine fail it. A first run found M40 among the ones handed to the browser and the browser passing it (in a real browser `animate` is on `Element.prototype`, one level higher than M40 looks): it is not flagged, and the node suites kill it |
| the reviewer's survivors M14, M38, M40b against the round-7 suites | SURVIVED, as reported; against these suites M14, M38, M40, M40b and the 45 other new mutants are KILLED. The element suite **alone** kills M38, M40b, the computed-key `getAnimations` and M39 |
| the new suites run against the round-7 card (`ECCO_MODE_SHELL_PATH` at a copy of the committed card) | **28 tests FAIL there**: 3 of 5 of `differential` (the whole read finds 4,771 texts that round 6 withheld and round 7 showed, rule by rule 2,821 lost matches, and the named five inputs), 9 of 14 of `budget`, 4 of `scan`, 5 of `static` (the wiring and the pins of the new structure), 4 of `perf` (the first snapshots and the cost per unit), 2 of `core` and 1 of `element` (the batched sweeps assert the budget was not used up, and the DOM says what was not read); the tripwires do not fail there because the committed card does not touch them |
| `probe8.mjs`, the five inputs and the seven more, round-6 card against round-7 card against this one | round 7 SHOWS six of the twelve (the connection pair after a bracket and after a comma, a URL token name of 65 before and after the key word, the JWT with a first segment of 600, the key block of 80); round 6 and this card withhold all twelve |
| `probe8b.mjs` (six attributes of 19990 characters and the state `healthy`) | round 7: `stateText` `[withheld]`, no unit, the title the entity id. This card: `healthy`, `kW`, `Intel status` |
| `perf8n.mjs` (discovered entities, each five attributes of 19999 characters of `eyJ-`), first snapshot of 1, 10, 50, 200 entities | round 7: 22, 197, 968, 3,878 ms. This card: 3, 5, 9, 12 ms. (The reviewer's `perf8.mjs` with the worst unit: the 5,000-entity row is in `perf.test.mjs`) |
| `perf.test.mjs`, the first snapshot of 16 families x 50, 200 and 5000 entities | the slowest of 48 runs: **61 ms** (a dotted run of digits, 5000 entities; bound 1000 ms); 5000 entities of twenty thousand values 75 ms, of 255-character near-miss ids 44 ms, 5000 small ordinary entities (all read) 63 ms; the worst shape costs 21 nanoseconds per unit, so a whole snapshot budget is **43 ms** |
| the rules alone, `perf.test.mjs` (2,875 measurements: 23 rules x 125 near-miss texts) | the slowest: 0.95 ms for 20000 characters (the dotted MAC on `0.0.0.`; round 7: 0.64 ms, round 6: 195 ms); the largest growth of a rule above 0.3 ms: 2.91 for twice the length (bound 3.5); the whole read of the worst text 0.96 ms |
| `differential.test.mjs` | whole read: 58,382 texts, the round-6 rules withhold 57,959, the card withholds all of them; rule by rule: 25,727 texts, 26,037 matches of the reference, none lost, every one of the 23 rules exercised; the round-7 forms lose 1,446 (url token), 81 (connection pairs), 40 (jwt), 482 (key block), 148 (webhook) and 624 (dotted MAC); about 4 seconds |
| `node preview/check-strip.mjs --require`, `--selftest` | PASS: 3192 of 3192 checks (unchanged: the strip, its places and attributes are as before); SELFTEST PASS: the card passes and 31 of 31 broken copies fail |
| `tools/tests/test_geek_mode_{catalogue,coverage,ledger,fixtures,privacy,example}.py`, `frontend/ecco-mode-shell/test/test_example_dashboard.py` | all pass (134, 219, 68, 102, 195, 35 and 31 checks; privacy gained 15, 3 s) |
| `tools/geek_mode_coverage.py --check`, `tools/gen_geek_fixtures.py --check` | both match a fresh regeneration (nothing the tools read or write changed) |
| `tools/validate_repo.py` | PASSED, with no edit to any pinned file (no demand for a manifest entry, a changelog line or a chain entry arose) |
| `tools/run_offline_tests.py --root tools/tests` | 21 of 21 pass (193 s), including the repository's public privacy scan over the new files and this document; the other roots (`ecco_core`, `health`, `intelligence`, `home-assistant`) read nothing this change touches and were not re-run; `registry/tests` neither (section 20.9, observation 8) |

### 20.11 Changes to existing tests and files (none weakens an assertion)

- `ecco-mode-shell.js`: 6 of the 23 patterns of `RULES` were rewritten (`jwt`, `key block`, `url token`, `connection pairs`, `MAC address (dotted)`, `webhook path`; the gates and the three pre-tests are as they were); `LIMITS` gained `snapshotChars`, `nodeChars`, `entityBaseChars` and `entityIdChars`; `redactValue` and `redactAttributes` add the values they visited to an optional `opts.work` (one helper, `countWork`); `partsFor` reads the state, the name and the unit before the attributes and keeps what the entity cost (`spent`); `prepare` also keeps the ids an alert watches; `makeRow` and `buildRow` make a row for an entity that is not to be read (`unread`, `spent`; `UNREAD_KEY` is exported); `buildSnapshot` ranks the entities, keeps one budget and decides before the cache is asked; `summarise` says how many were not read; the Geek header says so too. The stylesheet, the strip, the mode switch, the controller and every other DOM builder are untouched, so **no pin and no fixture was regenerated** (`style.pin.json`, the generated catalogue, ledger, live shape and fixtures are byte-identical; `--check` of both tools passes).
- **Pins changed from "shown" to "withheld" (the direction the owner asked for), each on purpose:**
  `scan.test.mjs`, the test "the bounds the rewrite introduced" of round 7 pinned three limits as texts the rules did NOT match (a JWT first segment of 600, a connection pair of 257 after a bracket, a URL token name of 65) and four at their edge as matched; it is replaced by "the bounds of round 7 are GONE", which asserts the opposite for the three (each now `true`) and, for each rule, adds a case beyond the old edge (a JWT of 5000 and 5000, a pair of 5000 and one after a comma, names of 3000 on both sides, a key block of 65 and of 80, a webhook host of 260, a dotted MAC with a letter 3000 characters after the address). The round-7 differential test's special case for the dotted MAC (the one narrowing, with its explanation of what was lost) is removed: the rule is in `EXACT`, so the test now asserts that **nothing is lost and nothing is gained**, which is stronger. `static.test.mjs`: six numbers of the table of unbounded quantifiers (jwt 1 to 2, key block 0 to 1, url token 1 to 2, connection pairs 7 to 4, dotted MAC 0 to 2, webhook path 2 to 3) and the line that pins the options of `partsFor` (it now carries `work`), with the comment that says why.
- **One pin changed from "withheld" to "shown", and why:** the last assertion of "the budget is per ENTITY" in `scan.test.mjs` said that the state of an entity whose attributes used the budget is withheld (round 7 read the state last). It now says the state is read first and shown, that the attribute past the budget is withheld, and, as a control that the order changed what is charged and not what is withheld, that a state shaped like a token is withheld although it is read first. This is the finding 5 fix.
- **Tests that built more than one snapshot budget of text in one snapshot were batched** (the snapshot budget is not what they test, and each asserts `unread === 0` on every batch, so every assertion is still made on every case): `core.test.mjs` (the sweep of the row paths, 100 cases per snapshot; the 2,000 entities of 4,500 characters: 350 fit and are read whole, and 2,000 now assert the new fact: about 440 are read and the rest say so), `scan.test.mjs` (the long sweep of the row paths, 30 cases per snapshot) and `perf.test.mjs` (the control: 400 entities of 4,200 characters). In each, every probe is still looked for in every batch.
- `element.test.mjs`: the `afterEach` asserts that no tripwire was touched; 3 tests appended (the tripwires are armed; both modes, every step; the DOM says what was not read). `minidom.mjs`: the tripwires, `recorded.apiCalls`, `resetRecorded` clears them. `static.test.mjs`: 5 tests appended and two imports. `perf.test.mjs`: 3 tests appended. `real-catalogue.test.mjs`, `coverage.test.mjs`, `strip-check.test.mjs`, `secrets.mjs`, `near-miss.mjs`, `helpers.mjs`, `css-guard.mjs`, `aria-guard.mjs`, `style-pin.mjs`: not changed.
- New files: `test/differential.test.mjs` (5 tests), `test/differential.mjs`, `test/reference-r6.mjs`, `test/budget.test.mjs` (14 tests), `test/member-guard.mjs`.
- `mutations.test.mjs`: 49 mutants appended (402 in all). **Retired: 4**, `AC12-r7-url-token-names-unbounded`, `-connection-pairs-value-unbounded`, `-jwt-segments-unbounded`, `-webhook-host-unbounded`: they replaced a bound of round 7 by `*` or `+`, and those bounds no longer exist; the round-6 form of each rule (the same break, written as it was, quadratic) takes their place (`AC12-r8-*-round-6-form`). **Re-anchored: 4**, with the same intent: `AC10-discovered-id-not-redacted` (the id line now carries the length cap), `AC10-extra-patterns-not-prepared` and `AC12-r7-state-own-budget` (the options line carries `work`), `AC10-webhook-services-form-dropped` (the second alternative is a look-behind). **One duplicate id renamed:** two mutants were both called `AC6-not-in-inverted`; the file of a mutant is named by its id, so only the second was ever run, and the first (`state_not_in` inverted) was never tested; the second is now `AC6-attribute-not-in-inverted`, a test says every id is used once, and both are killed. `budget.test.mjs` joined the suites every mutant runs; `differential.test.mjs` is run against the baseline and the nine mutants flagged `diff: true`; `AC6-r8-M38` and `AC6-r8-M40b` are `browser: true` (the headless check fails them; M40 is not, because in a real browser `animate` is one level higher on the prototype chain and that mutant hides nothing there, so the node suites alone kill it).
- `tools/tests/test_geek_mode_privacy.py`: five scanner patterns changed (the e-mail domain, the JWT-like, the JWT form of the token-shape scanner, the webhook host, the dotted MAC; section 20.8); the agreement checks of the webhook rule, the dotted MAC and the JWT were rewritten for the new rules (the webhook one as a documented transformation of the same text; no check was dropped) and the snapshot budget was added; the "narrower" branch of the round-7 differential block was removed (the dotted MAC is exact); block [8] was appended. The other Python suites and tools are untouched.
- `README.md`: a paragraph, the test table (three new rows, the static, perf, element and mutation rows). This document: section 20, and one-line notes in sections 19.2 and 19.8 that round 8 supersedes the bounds.

## 21. Review round 9 (15 Nov 2026): findings and fixes

The ninth review found **two MAJOR holes in the test net** (neither is a defect of the shipped card), **one MINOR honesty gap in the shipped card** and **one NIT in the mutation runner**. The card behaves correctly on the two MAJORs today; what was missing was the net that would notice if it did not. Closing the round found two more things, both about the machine and not about the card: the first scheduler of the new net had no bound and ran away, and a failing comparison of a DOM node in the old tests could take the memory of the PC (present since round 1; finding 5). Each finding was reproduced first, against the committed round-8 tree (section 21.8), then closed **by class**, not by instance: the new tests fail on the mutants, the mutants are in the proof, and nothing was weakened. The one change to shipped code is small (section 21.5). Nothing pinned, sealed or deployed was edited, nothing is live, nothing was pushed.

### 21.1 The findings and what was done

| # | Severity | Finding | Fix | Proof |
|---|---|---|---|---|
| 1 | MAJOR (test gap) | **The async-hide class.** Mutant E05 (a promise continuation empties the strip's text one tick after the switch to Geek Mode) and E08 (an async function that awaits and then empties it) survived all ten node suites and `check-strip --require`; E07 (the same inside the renderer) was killed only by accident, by the burst-coalescing test. Every strip test looked at the strip **in the same task** as the click or the update. The owner's rule is that a safety alert is visible in both modes **at all times** | Five nets that do not ask "is this a known way to hide the strip" (section 21.2): a **static pin** of every place the card may defer or schedule work, each with its reason; a **scheduler** that records and runs everything the card schedules, **bounded** so that it cannot run away (section 21.3); **settling** after every switch, update and tick in every AC6 test and in the `afterEach` of the element suite; **THE TOUR**, a full session in both modes with the strip compared after every step; and a second measurement in the headless check after a zero-delay timer and two animation frames | `test/async.test.mjs` (27 tests), `test/async-net.mjs`, `test/element.test.mjs` (the AC6 tests, the `afterEach`, the tripwire hook, THE TOUR), `preview/check-strip.mjs` (38 broken copies, seven new), `test/mutations.test.mjs` (30 mutants) |
| 2 | MAJOR (test gap) | **The cache class.** Mutant B11 (a read reused from the parts cache is charged nothing) survived every suite: the DETERMINISTIC test built its two snapshots at the same clock, so the row cache hit and the parts cache (the normal path on every timer tick, when only the age moves) was never asked | **Warm against cold, after every step of a history** (section 21.4): the snapshot from warm caches must equal, field for field, the snapshot a cold read of a deep copy gives, at NOW, +61 s, +1 h, +2 h, after a one-entity update, an entity that goes and comes back, a new entity that sorts first, a catalogue swapped under the same states, and under budget pressure; the same for the rows of the Geek surface | `test/cache.test.mjs` (5 tests), `test/element.test.mjs` (the surface), `test/budget.test.mjs` (unchanged); 22 mutants, one or more for **every** cache of the card |
| 3 | MINOR (shipped) | **Honesty.** `summarise` took the problem count as `problems - unread`, so an entity that was past the snapshot budget **and** unavailable (or stale) vanished from the Production problem sentence: five unavailable data points among ten unread were never said to be unavailable | The problem sentence counts the rows whose **status is not live**, read or not (`counts.notLive`); the unread sentence counts the rows that were not read; an entity in both is in both (section 21.5) | `test/cache.test.mjs` (1 test); 6 mutants |
| 4 | NIT | **The wall-clock kill.** E08 was reported killed at four processes at a time by a timing assertion and survives at one; a kill attributed only to a timing test can hide a survivor | **The runner rule** (section 21.6): a mutant whose every failing test is a `[wall-clock]` test is run again, alone, one file at a time, and counts as killed only if it fails again; static test keeps the tag honest | `test/mutations.test.mjs` (the rule and a test of its logic), `test/static.test.mjs` (1 test) |
| 5 | MAJOR (test infrastructure, found while closing this round; present since round 1) | **A failing comparison of a DOM node took the machine's memory.** The mutant `AC6-strip-inside-production-body` (round 1) makes `assert.equal(strip.closest('[data-ecco-body]'), null)` fail; Node builds the failure message by deep-inspecting the node (depth 1000, custom inspection off), and a node whose parent, document and listeners were enumerable properties is walked **together with the whole page**: the element and real-catalogue suites went past 5 GB in two seconds, with the committed round-8 tests too. The mutation proof ran six such processes at a time | The references that lead out of a node (`parentNode`, `childNodes`, `ownerDocument`, listeners, style, the host of a shadow root, the document's registry) are **not enumerable** in the test DOM; they are still readable and writable. A failing comparison now shows a node's tag and attributes and nothing around it (section 21.3) | `test/async.test.mjs` (1 test, with a control that makes the hazard visible), `test/minidom.mjs`; the mutant is killed by 148 tests in two seconds |

### 21.2 The async-hide class

**The class** is "work that the card defers, however it defers it": a promise continuation, an async function, a microtask, a timer of any delay, an animation or idle callback, an observer callback, a listener that fires later, a chain of them, or a hide placed inside one of the card's own allowed callbacks. A test that looks in the task of the action cannot see any of them.

**(a) The static pin** (`test/async.test.mjs`, `test/async-net.mjs`). A one-pass reader of the card's source (strings, templates, regular expressions and comments blanked, line numbers kept) looks for 29 tokens on every line: `Promise`, `then`, `catch`, `finally`, `async`, `await`, `queueMicrotask`, `setTimeout`, `setInterval`, `setImmediate`, `clearTimeout`, `clearInterval`, `requestAnimationFrame`, `cancelAnimationFrame`, `requestIdleCallback`, `cancelIdleCallback`, `MutationObserver`, `ResizeObserver`, `IntersectionObserver`, `PerformanceObserver`, `MessageChannel`, `nextTick`, `scheduler`, `Worker`, `Atomics`, `AbortSignal`, `addEventListener`, `removeEventListener` and an `on...=` property handler. Every occurrence must be on the enumerated list `ALLOWED_ASYNC_SITES`, as the exact line (comments gone, white space folded), the token, the number of times and **why it exists**; anything new, anything changed and anything gone fails until a person decides and edits the list in the same commit. The 14 entries of the card today:

| Site (function) | Why it exists |
|---|---|
| `on()`: `el.addEventListener(type, fn)` (1) | the one helper every control is wired with (switch, search box, filters, rows, copy, export, open); user events only, each handler runs in the task of the click |
| `connectedCallback()`: `window.addEventListener('location-changed', ...)`, `'pagehide'`, and the feature test around them (3) | Home Assistant tells the page the path changed, or the page is left or frozen: the mode returns to Production (a reset, never a hide) |
| `_unlisten()`: the two `removeEventListener` calls and their feature test (3) | the pair of the registrations above, on disconnect |
| `connectedCallback()`: `typeof ResizeObserver` test and `new ResizeObserver(...)` (2) | the only observer: a card shown in a 0 x 0 box returns to Production; the callback only resets the mode and touches no alert |
| `_startTimer()`: `setInterval(() => this._onTimer(), ms)` (1) and `_stopTimer()`: `clearInterval` (1) | the one timer slot: the 15 s age tick and, after a burst, one short flush; both only re-run `_refresh`, which re-derives the strip from the same snapshot in both modes |
| `_mountChild()`: `helpers().then(...).catch(...)` (2) | Home Assistant card helpers build a child card asynchronously; the continuation attaches it inside its own region and never touches the strip |
| `_copy()`: `clip.writeText(text).then(...)` (1) | the clipboard answers asynchronously; the continuation writes one status line in the Geek surface |

There is no `Promise`, no `async`, no `await`, no `setTimeout`, no animation frame, no idle callback and no other observer in the card, and the pin says so by count. 41 planted forms are the negative controls (the reviewer's E04, E05, E07, E08, a thenable, `for await`, a second interval, a timer reached through `window`, `setImmediate`, `process.nextTick`, every observer, a message channel, `scheduler.postTask`, `AbortSignal.timeout`, a worker, `Atomics.waitAsync`, an on-property handler, a listener on the strip and on the window, a duplicate of an allowed line, and an allowed line **changed** so that the same call also empties the strip). All are refused.

**(b) The scheduler** (`installScheduler`). It is installed before the card is evaluated and wraps `setTimeout`, `setInterval`, `queueMicrotask`, `Promise.prototype.then`, `requestAnimationFrame`, `requestIdleCallback` (Node has neither: they exist now, so code that asks `typeof requestAnimationFrame` is no longer dormant), the three observers, `addEventListener` on the stand-in elements and window, and the same functions on the stand-in `window` (so a timer reached as `window[name]` with a name built at run time is recorded too). Every call made while the card is on the stack is recorded with the card's own line. **`flush()` then runs everything that is waiting, now, whatever its delay**: the macrotask (which runs every microtask and promise continuation before it), every timeout, every interval once, every frame and idle callback, every observer callback (a normal box for the resize observer, a child list change for a mutation observer, an intersecting and a non-intersecting entry for an intersection observer), and, with `events`, one event of every kind the card listens for on the element it listens on, and it calls `after(what)` after each of those, so the strip can be compared after **every** step. `stripFingerprint` is the whole subtree of the strip (tags, attributes, text), every ancestor up to the host with its own attributes (hidden, inert, aria-hidden, role ...; only the mode and the theme are left out, because they change on purpose) and the elements before it in its shell: a strip that is emptied, hidden, moved, muted, wrapped or pushed down is a different fingerprint. Its own tests (`async.test.mjs`) plant 16 ways to defer a change to a synthetic page and assert that the scheduler reaches each (so the net has teeth), and that the fingerprint sees ten ways for the strip to differ.

**(c) Settling.** In every AC6 test of `element.test.mjs` (each alert, each way an entity can be unavailable, unknown or missing, the calm strip, the announcements, the data following, the ageing, the screen-reader checks, the placement checks, the configuration notices, the inline-style check, the outside-entity watch) each switch, each hass update and each timer tick is followed by `settled()`: the scheduler runs everything, and the strip must be **exactly** what it was in the task of the action, and visible. The `afterEach` of the whole file does the same for every live element of every test, whatever mode the test left it in. The tripwire test (round 8) now flushes after every step too. The negative-control tests that plant damage on a live element drop that element afterwards, so the check does not see the plant mended by the card's own refresh.

**(d) THE TOUR** (`AC6 [r9] THE TOUR`). A full session on one element with three alerts: Production fresh, Geek Mode with every row open, a search, a copy and both exports, four hass updates with theme changes and ticks, five switches, the hidden-box observer firing a 0 x 0 box (the mode returns to Production). After **each** of more than 100 steps the strip fingerprint is compared with the first one and the strip is asserted visible. It also asserts that the card scheduled something through each of `setInterval`, `ResizeObserver`, `addEventListener` and `then` (so the net looked at them), that **every place the card scheduled from is on the enumerated list** (the dynamic half of the pin: a computed name, an alias or a captured reference is seen here whatever it looks like in the source), that the age tick is still waiting while the card lives and that **nothing is left scheduled after disconnect**, and that the scheduler stayed under a quarter of each of its own bounds.

**(e) The headless check** (`preview/check-strip.mjs`, `strip-check.html`, `strip-check-lib.mjs`). Each state is measured twice: in the task of the switch, and again after a zero-delay timer, two animation frames and the microtasks between them. `compareSettled` fails the second measurement if the strip is gone, moved or resized, shows other lines, other text, another count, other accessibility attributes (own and every ancestor's), another role on a line, or another mode; a page that forgot to wait cannot pass (`requireSettled`). The self-test table has seven new broken copies (E04, E05, E05c, E07, E08, E09, E14) and catches **38 of 38**. **A limit, stated plainly:** in the headless virtual-time browser the animation frames are mostly not delivered (the report counts them: of the 48 settled measurements the browser delivered both frames for none, one frame for two, and none for 46), so the wait is given up after 250 ms of the page's own clock. Microtasks, promise continuations, async functions, timers up to 250 ms and observer callbacks have run either way, and the self-test proves that those are caught; an animation-frame hide and a timer longer than 250 ms are left to the node scheduler, which runs both. `--virtual-time-budget` was raised from 20000 to 600000 so that the second measurement fits. Adding `--run-all-compositor-stages-before-draw` was tried and changed nothing, and was not kept.

**(f) The mutants** (30, `AC6-r9-E04` to `E32`): a microtask (E04, E25, E28), a promise continuation that empties, hides, sets aria-hidden or moves the strip (E05, E05b, E05c, E07 in the renderer, E24 a deferred empty render, E26), an async function (E08), a zero-delay timer (E09, E27), a timer of twenty seconds (E10), a second interval (E11), an animation frame and an idle callback behind a `typeof` test (E12, E13), a mutation, intersection and resize observer (E14, E15, E16), a listener on the strip and on the window (E17, E18, E31), an on-property handler (E32), a timer reached through `window[name]` with the name built from pieces (E19), state that builds up (the fourth render empties the strip, E20), the timer path (E21), the age tick callback (E30), a hide inside each allowed site (the helpers continuation E22, the clipboard continuation E23, the click handler E25), and a chain of three (timer, microtask, frame; E29). Five are also handed to the headless browser.

### 21.3 The two runaways of this round, and a scheduler that cannot run away

**What happened.** Two earlier attempts of this round were killed because the PC ran out of virtual memory (twice in 20 minutes, with a restart each time). There were **two separate runaways**, and the second was found only because a memory guard (a wrapper that caps every node process at a 3 GB heap and kills it above 5 GB, logging who it was) was in place for the final runs.

**Runaway A: the first scheduler.** It had no bound on anything and kept every listener registration for ever, including those on elements that had long left the page. A flush with `events` fired one event of every kind at every registration, a fired click re-renders part of the Geek surface, the re-render registers new listeners, and the next flush fires those too. Reproduced afterwards in a scratch copy under a 400 MB heap with a counter in the old code: the registry held 29,931 registrations when THE TOUR began, and over the tour's six consecutive flushes it grew 5, 358, 886, 2,241, 6,123, 16,859 and the process died of memory in under a second (in the first attempt the guard logged 1 GB and 2 GB six seconds apart). The tour run alone with a test-name filter does **not** run away (55 ms): it needs the registrations of the tests before it, which is why it was not seen at once.

**Runaway B: a failing comparison of a DOM node (present since round 1).** `assert.equal(node, null)` that fails builds its message by inspecting both values with a depth of 1000, no limit on arrays and custom inspection off. A node whose parent, document and listeners were enumerable properties was walked **together with the whole page**. The mutant `AC6-strip-inside-production-body` (round 1) makes exactly `assert.equal(strip.closest('[data-ecco-body]'), null)` fail, and the element and real-catalogue suites went past 1 GB in 0.4 s and past 5 GB in two seconds, **with the committed round-8 tests too** (reproduced against the extracted round-8 tree). The mutation proof ran six such processes at a time. The first full run of the proof of this round was stopped on the guard's first kill (the rule of the round is to stop and fix on any kill); the fix is in section 21.1 finding 5: the references that lead out of a node are not enumerable in the test DOM (`quiet` in `test/minidom.mjs`), so a failing comparison shows the node's tag and attributes and nothing around it. After it the same mutant is killed by 148 tests in two seconds with no growth. In the final run of the proof the guard was never above its cap: one process crossed 1 GB (`perf.test.mjs` under the mutant that removes the snapshot budget, which is what that mutant is for) and nothing was killed.

**The rule of this round.** A net that can eat the machine is worse than no net. Every kind of work the scheduler records, runs or fires has a hard maximum, and when one is reached it **throws `SchedulerBound`** (naming the bound, the limit and what was reached) in well under a second; from then on every scheduling call of a tracked caller throws the same error until the next test begins, so a card that catches the error in its own handler cannot keep allocating, and the next `flush()` raises the stored error again, so it cannot be hidden either.

| Bound | Value | What it stops |
|---|---|---|
| `maxRecords` | 4000 | different places (an API and a line of the card) remembered per test; the same place seen again is only counted, so the records cannot grow with volume |
| `maxListeners` | 4000 | listener registrations held at one time; when it is reached those on elements that have left the page are dropped first (they can never be fired), and what is still over is alive, and is a runaway |
| `maxPending` | 500 | timers, frames and idle callbacks waiting at once |
| `maxCallbacksPerFlush` | 1000 | timers, frames, idle and observer callbacks that one flush runs |
| `maxEventsPerFlush` | 2000 | events that one flush fires |
| `maxRounds` | 6 | rounds of one flush: **timers, frames or idle callbacks still waiting after the last round mean the card keeps re-arming them**, and the flush throws |
| `maxWorkPerTest` | 200000 | the sum of everything above, per test (a record, a registration, a callback, an event, a flush, a microtask, a continuation) |

The structural changes: events are fired only at listeners that **exist when the flush starts**, each (element, type) pair once, and only while the element is still on the page (a listener on an element that was replaced is forgotten, because it can never be reached); what the events register is not fired by the same flush; the observer arrays are copied before they are run (a callback that makes a new observer cannot extend its own loop); a timer that only Node's own test runner made is neither recorded nor run early. Only calls made by the card or by the test files are the scheduler's business.

**Proof** (`async.test.mjs`): ten synthetic runaway cards, each stopped by the named bound after a bounded amount of work, each with the error remembered and raised again by a later flush: a timer that re-arms itself (`maxRounds`), an animation frame that asks for the next frame (`maxRounds`), an interval whose callback starts another interval (`maxPending`), a microtask that queues the next one for ever and a promise continuation that does (`maxWorkPerTest`), a click handler that makes twenty buttons with the same handler (twentyfold growth per flush: `maxEventsPerFlush`, and, with room to fire, `maxListeners`), a window handler that registers three more listeners (`maxListeners`), a resize observer whose callback makes another (`maxCallbacksPerFlush`), and a listener that swallows the error. A second test asserts that after a bound every further call throws the same error and that `beginTest` forgets it. A third (`[wall-clock]`) asserts that each is stopped in well under a second and that the heap grows by less than 300 MB in all (measured: the slowest 33 ms, no measurable growth). The element tests print the peaks the real card uses over the whole file: 5,968 units of work in the busiest test, 7 different scheduling sites, 15 timers waiting at once (the busiest test mounts fifteen cards, one age tick each), 30 callbacks in the busiest flush, 42 listener pairs alive when the tour's first flushes began (most of them are dropped as the fired events replace their elements, so 5 events were fired by the busiest flush), and THE TOUR asserts that the whole session stays under a quarter of each bound. The Geek surface wires most controls by delegation, so few listeners exist at once.

**How the suites are run** (the owner's machine rules for this round): every node command goes through a wrapper that sets a 3 GB heap and a per-process guard that kills any node process above 5 GB within 100 ms and logs it; the mutation runner's children inherit both. The runner's children are now held to `--test-concurrency=2` each (they ran as many files at once as the machine has cores, in each of six runs of the pool).

### 21.4 The cache class

**The class** is "a cache returns something a cold read would not": stale, free or from the wrong key. So the tests do not name a cache. The card has seven: the compiled extra key patterns (`EXTRA_CACHE`), the per-entity key decisions of one read (`ctx.keys`), the prepared catalogue (`PREP`), the read of one state object (`PARTS`: the redacted attributes, the attribute rows, the search text and **what the read cost the snapshot**), the built row (`ROWS_BY_STATE`, `ROWS_BY_SOURCE`) and, in the Geek surface, the rendered row (`this.cache`, by signature).

`test/cache.test.mjs` walks histories and asks, after **every** step, whether the snapshot built from warm caches (the same state and catalogue objects as the step before, as Home Assistant keeps them) equals, field for field, the snapshot a cold read of a deep copy gives, and whether a second warm read at the same clock is the same again. "Equal" is every field of every row (state, age, status, flags, order, unread, spent, attributes, the redacted values, the search text, the signature, normalising only the sequence number of the read), the counts, the groups, the alert inputs, the alerts and the Production sentence. The dimensions: the clock (NOW, +61 s, +1 h, +2 h), a one-entity update, an entity that goes and comes back as a new object, a new entity that sorts **before** the others (every later row moves), one that sorts last, a catalogue swapped under the same state objects (a title, a description, a different set of secret key fragments) and swapped back, the same entity described by two sources, two entity ids that share one state object, every Intelligence fixture with 300 decoys beside it at its own clock, a minute later and an hour later, and the budget (eight early entities grow to 20000 values each so that a cached one is now past the budget; they shrink back to the very objects they were; five early ones are replaced by small ones so there is room again). The DETERMINISTIC test builds its snapshots at NOW, NOW + 61000 and NOW + 3600000 (the row cache misses on the clock, the parts cache hits, and the test asserts that no part was rebuilt), and after a one-entity update, and asserts identical keys, unread flags, spent values and statuses; a read from the cache costs what the read cost. In `element.test.mjs` the Geek surface of a long-lived element is compared, character for character, with a freshly mounted one at the same clock and states after each of eight steps.

**The mutants** (22, `AC12-r9-`): `B11` (a cached read is free), `B11b` (half price), `B11c` (reused under another catalogue), `B11d` (cached by entity id, not by state object), `B11e` (reused for another source), `R01` to `R07` and `R09` (a row reused whatever the clock says, for any distance in time, across a status edge, with a stale order, free, under another catalogue, for another ledger key, or for an entity past the budget), `X01` to `X03` (the extra patterns, the prepared catalogue and the key decisions are those of the last read), `G01` to `G06` (the signature of a Geek surface row leaves out the age, the state, the read, the status or whether the row is open, or the surface never rebuilds a row). All are killed.

### 21.5 The honesty fix (the one change to the shipped card)

`buildSnapshot` counts one more thing, `counts.notLive`: the rows whose **status** is not live (stale, unavailable, unknown, not measured, simulated, unverified), whether or not the snapshot read the entity. `summarise` says it in its own sentence ("N data points are stale, unavailable, simulated or unverified. Geek Mode lists them.") and says the unread rows in another ("N data points were not read: ..."). An entity that is both is in both. `counts.problems` (the Problems filter) is unchanged. Reproduced: 30 entities, the last 5 unavailable, 10 past the budget: the round-8 note said only "10 data points were not read"; the new note says both. The test covers an entity that is unavailable and unread, stale and unread, live and unread (second sentence only), unavailable and read (first sentence only) and nothing to say. **No pin and no fixture changed**: the stylesheet, the strip, the switch, the controller and every DOM builder are as they were (`style.pin.json`, the generated catalogue, ledger, live shape and fixtures are byte-identical; `--check` of both tools passes).

### 21.6 The runner rule

Tests that assert how long something took carry `[wall-clock]` in their title (22 of them: all of `perf.test.mjs`, and every test of another file that reads the clock; `static.test.mjs` fails if a test that reads the clock lacks the tag, or the tag is on a test that does not). `mutations.test.mjs` reads the failing titles of each mutant run; a mutant whose every failing test is `[wall-clock]` is run again, alone, `--test-concurrency=1`, and **counts as killed only if it fails again**; a run that failed with no test named (a crash, a file that did not load) is not a timing failure, and a mutant killed by any behavioural test needs no second run. The logic is tested on made-up outputs, the runner prints which mutants needed the second run, and a mutant that survives alone is reported as SURVIVED.

**A time limit for a nested run, and a second chance (found by the last full run).** In one of three full runs of the proof, one nested test-file process of one mutant went idle (no CPU, no open port) and stayed so for thirty minutes, with every other run long over; the same mutant and file then ran clean three times alone, so it was not the card and not a test (the file is synchronous). The runner had no time limit. It now has one (300 s for a nested run, 900 s for the baseline): a run that does not finish is killed with its whole process tree (`taskkill /T` on Windows, checked on this PC), is run once more alone, and the second run is the result (named in the output as having been retried); a mutant whose run hangs twice is reported by name and counts as killed, because a suite that never ends fails any pipeline. A hang is never mistaken for a timing failure. The logic has a test on made-up results.

### 21.7 What the owner needs to know

1. **Nothing the owner has to do.** No pinned, sealed or deployed file was edited; no integration step of section 8 changed. Production Mode is unchanged. The shipped card changed in two places only (`counts.notLive` in `buildSnapshot`, and the two sentences of `summarise`).
2. **The pin is now a process, not an accident:** the day someone adds a timer, a promise, an observer or a listener to the card, `async.test.mjs` fails until the site is added to `ALLOWED_ASYNC_SITES` with its reason. That is intended.
3. **Observation (limit):** the headless browser check cannot deliver animation frames (section 21.2 (e)); an animation-frame hide is caught by the node scheduler, which runs frames, not by the browser. A timer longer than 250 ms is likewise the scheduler's.
4. **Observation:** events the scheduler fires are synthetic events at the registered target; the Geek surface wires most of its controls by delegation, so the number of listener pairs alive when the tour fires them is small (42 at most). The pin and the dynamic list in the tour are what cover a listener added later.
5. **Process note (this round):** two attempts were lost to the runaway scheduler of section 21.3; the registry suite and the other repository suites were not re-run (they read nothing this change touches, as in rounds 6 to 8).

### 21.8 Results of the runs

Every node command of the round went through the guard wrapper (3 GB heap, kill above 5 GB), one suite at a time (two files at once at most), and the mutation proof alone and last.

| Run | Result |
|---|---|
| the reviewer's survivors E05, E07, E08, B11 against the round-8 tests (element, static, budget, real-catalogue, coverage: 359 tests) | E05, E08 and B11 SURVIVE (359 of 359 pass), as reported; E07 is killed by one test, by accident (the burst-coalescing test) |
| the same four, against these suites (element, async, cache, budget) | all KILLED: E05 61 failing tests, E07 42, E08 61, B11 4 (the four cache tests) |
| the new suites against the committed round-8 card | one test fails there: the honesty test (the problem sentence); the rest pass, because the two MAJORs are gaps in the net, not defects of the card |
| `probe9-summary.mjs` (30 entities, the last 5 unavailable, 10 past the budget) | round 8: "10 data points were not read" and nothing about the five. This card: both sentences |
| `probe9-cache.mjs` (40 entities of about 100,000 characters) | round 8 card: unread 20, 20, 20, 20, 20. With B11: 20, 20, 0, 0, 0 (a later snapshot reads every entity past the budget) |
| the old unbounded scheduler, in a scratch copy under a 400 MB heap, with a counter | the registry held 29,931 registrations at the tour; over the tour's flushes 5, 358, 886, 2,241, 6,123, 16,859; out of memory in under a second (section 21.3, runaway A) |
| `AC6-strip-inside-production-body` against the round-8 tests and against these, under a 400 MB heap and a 1 GB guard | before the fix of finding 5: past 1 GB in 0.4 s, both suites killed by the guard. After: 108 failing tests in real-catalogue and 40 in element, in 1.7 s and 4.5 s, no growth |
| `node --test`, one file at a time: core 157, element 125, async 27, cache 5, coverage 4, static 60, real-catalogue 159, strip-check 14, scan 16, perf 11, budget 14, differential 5 | all pass (core 4.8 s, element 6 s, perf 20 s, differential 3.4 s, the others about a second); no guard event |
| `node --test --test-concurrency=2 test/mutations.test.mjs` (alone, last: 480 tests, all pass, 1,128 s) | **460 of 460 mutants killed by the node suites alone** (the 402 of round 8 and 58 new: 30 async-hide, 22 cache, 6 honesty). Six were killed only by wall-clock tests in the parallel run and were run again alone by the runner rule (`AC12-rebuild-every-row`, `AC12-flush-timer-not-restored`, `AC10-r6-K02-unbounded-slice`, `AC12-r8-connection-pairs-round-6-form`, `AC12-r8-webhook-round-6-form`, `AC12-r8-mac-dotted-eager-lookahead`): all six were killed again, so none was a kill by load. The headless check fails all fourteen browser-flagged mutants. An earlier full run had one failure (E14, dormant in a real browser, section 21.9), fixed; another went idle in one nested process and was stopped by hand (section 21.6, now a time limit with one retry); in this final run nothing hung or was retried, the memory guard killed nothing, and one process crossed 1 GB (`perf.test.mjs` under the mutant that removes the snapshot budget) |
| `node preview/check-strip.mjs --require`, `--selftest` | PASS: 6816 of 6816 checks (3192 before: every state is measured twice and the pairs are compared); SELFTEST PASS: the card passes and **38 of 38** broken copies fail (31 before, seven new). The browser delivered both animation frames for none of the 48 settled measurements, one frame for two, none for 46 (section 21.2 (e)) |
| `tools/tests/test_geek_mode_{catalogue,coverage,ledger,fixtures,privacy,example}.py`, `frontend/ecco-mode-shell/test/test_example_dashboard.py` | all pass |
| `tools/geek_mode_coverage.py --check`, `tools/gen_geek_fixtures.py --check` | both match a fresh regeneration (nothing the tools read or write changed) |
| `tools/validate_repo.py` | PASSED, with no edit to any pinned file (no demand for a manifest entry, a changelog line or a chain entry arose) |
| `tools/run_offline_tests.py --root tools/tests` | 21 of 21 pass (186 s), including the repository's public privacy scan over the new files and this document; the other roots (`registry/tests`, `ecco_core`, `health`, `intelligence`, `home-assistant`) read nothing this change touches and were not re-run |


### 21.9 Changes to existing tests and files (none weakens an assertion)

- `ecco-mode-shell.js` (shipped): `buildSnapshot` counts `counts.notLive`; `summarise` counts the problem sentence from it and the unread sentence from `counts.unread` (13 lines). Nothing else; **no pin and no fixture regenerated**.
- **New files:** `test/async-net.mjs` (the pin, the bounded scheduler, the fingerprint), `test/async.test.mjs` (27 tests), `test/cache.test.mjs` (5 tests).
- `test/minidom.mjs`: `quiet`, and the references that lead out of a node (and the shadow root's host, the document's registry, the window's listeners) are not enumerable. They are still readable and writable; nothing that read them changed.
- `test/element.test.mjs`: the AC6 tests became `async` and settle after each switch, update and tick (every assertion kept; several have one added); the `afterEach` flushes and compares the strips; `beforeEach` begins the scheduler's test; the tripwire test flushes after each step; the negative-control tests that plant damage on a live element drop it afterwards; THE TOUR and the Geek-surface cache test were appended (125 tests, 123 before). Three timing tests gained the `[wall-clock]` tag in their titles.
- `test/core.test.mjs`, `test/perf.test.mjs`, `test/real-catalogue.test.mjs`, `test/scan.test.mjs`: **titles only** (the `[wall-clock]` tag on 18 tests that assert how long something took; no body changed).
- `test/static.test.mjs`: one test appended (the tag is on exactly the tests that read the clock). `test/strip-check.test.mjs`: three tests appended. `preview/check-strip.mjs`, `preview/strip-check-lib.mjs`, `preview/strip-check.html`: the second measurement (`compareSettled`, `requireSettled`, `settle`), seven broken copies, `--virtual-time-budget` 20000 to 600000.
- `test/mutations.test.mjs`: 58 mutants appended (460 in all; none retired, none re-anchored); `async.test.mjs` and `cache.test.mjs` joined the suites every mutant runs; the runner rule (section 21.6) and a test of its logic; the children of the runner run at `--test-concurrency=2` (one for the second run) and have a time limit with one retry (section 21.6). Of the new mutants five are `browser: true`. A first run found one of them (E14, an observer that watches only the direct children) dormant in a real browser, because nothing changes the direct children of the shell after the switch; it now watches the subtree, as its broken copy in the self-test does, and the headless check fails it.
- `README.md`: a paragraph, the run commands (`--test-concurrency=2`), two table rows and the mutation row. This document: section 21. `tools/` and `tools/tests/`: not changed.
