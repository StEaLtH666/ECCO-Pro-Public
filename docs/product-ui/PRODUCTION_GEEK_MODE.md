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
   queries; IP and MAC addresses; latitude, longitude and location keys; connection strings; the catalogue's extra patterns. They are
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
| AC7 | same data in Production and Geek | one catalogue, one fixture format | changing-hass test of the one adapter |
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
- Nothing ran in a real Home Assistant: the alert automations' live entity ids, the reserve helper's attributes, the real card helpers and
  the real theme are confirmed from code, the one shape listing and headless Chrome only.

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
`python -I -B -X utf8 test/test_example_dashboard.py`; the preview in headless Chrome (section 12.4).

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
