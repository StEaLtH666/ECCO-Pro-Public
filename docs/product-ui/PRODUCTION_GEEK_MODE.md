# Production Mode and Geek Mode (offline proof on the ECCO Intelligence tab)

Status: DESIGN AND DATA SIDE of the first offline proof. Nothing here is deployed, installed or registered; nothing touches Home
Assistant, the dongle, the inverter or InfluxDB; no firmware is involved. The proof is one representative tab, the standalone ECCO
Intelligence SHADOW view, so that the idea can be judged before any other tab is converted.

This document records the design, the invariants both halves of the proof must keep, the acceptance cases, how to apply the shell
to another tab, what the proof does not do, and the integration steps that are left to the owner. The numbers quoted are those of
this change; the generated ledger (`docs/product-ui/GEEK_MODE_COVERAGE_LEDGER_intelligence.md`) is the authority for the current ones.

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
catalogue plus its existing card as a child, not a second dashboard implementation. The shell itself (`frontend/ecco-mode-shell/
ecco-mode-shell.js`) is written separately; this change delivers its data side: the catalogue, the information coverage ledger,
the synthetic fixtures and the Python tests, and these notes.

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
| `tools/tests/test_geek_mode_*.py`, `tools/tests/_geek_scratch.py` | five suites and their shared helper |

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
- Alert conditions `when` are exactly one of `{state_in: [..]}`, `{state_not_in: [..]}`, `{unavailable: true}`,
  `{attribute: name, in: [..]}`. The intended meaning of `{unavailable: true}` is: the entity's state is `unavailable`, or the entity
  is missing from `hass.states` (a declared entity that is missing is as bad as an unavailable one; it must not hide an alert).
  An `in` list may mix booleans and texts (`applies_nothing` is listed as false, "false" and "False") so a strict or a stringified
  comparison both match. The shell's tests should pin both readings.
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
   is visible in Geek Mode with any write action is rejected (`validateChildCards`). Geek Mode grants no extra write permission,
   exposes no installer-only write and bypasses no backend confirmation.
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

"This change" is the data side delivered here and proven by the Python suites. "Shell" is the card side, written and tested in the
shell worktree (`frontend/ecco-mode-shell`), against the same catalogue and fixtures.

| AC | Behaviour | This change | Shell |
|---|---|---|---|
| AC1 | default Production on first render | - | first-render test |
| AC2 | a reload (a fresh element) is Production | - | fresh-element test |
| AC3 | enter, switch to Geek, leave (location-changed, disconnect, hidden, pagehide) and return: Production | - | one test per leave signal |
| AC4 | two shell instances never share or leak a mode | - | two-instance test |
| AC5 | every interaction makes zero calls; no storage | the catalogue and fixtures are plain data | throwing hass stub; static pin for storage; behavioural test |
| AC6 | the alert strip shows every alert identically in both modes, over unavailable and unknown | 15 alerts derived from the contract (every status and data-quality state alerted or listed as none); every alert names a catalogued entity; fixtures for each alert state (`stale`, `paused`, `self-test-failed`, `unavailable`, `watchdog-stale`); `test_geek_mode_catalogue.py` [3], `test_geek_mode_fixtures.py` [5] | parametrised over every alert and over unavailable and unknown states |
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
- It does not write the shell itself (`ecco-mode-shell.js`) or its tests; those are written separately.
- It does not show information that is not a Home Assistant state or attribute: the diagnostics download, the recorder history, the
  logs, the registries, the notifications, the scorecard database and the owner's site file are listed as exceptions, each with a
  note on what exposing it would take (a new read-only diagnostic entity is a contract change request).
- It does not generate the descriptions: they are written by hand and checked for presence and for orphans, not for wording.
- It does not prove the card-side behaviours (AC1 to AC7, AC9 to AC14, AC16): those belong to the shell's tests.

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
- A contract-version mismatch ("output not recognised") cannot be written as an alert with the agreed `{attribute, in}` form (it
  would need "not in"). The package's own alert and the Production card's notice cover it; the catalogue alerts on
  `applies_nothing` being false instead. A `not_in` form would be a schema change.
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

## 10. Findings for the owner, and deviations from the brief

Findings (also in the ledger's section 2 where the tool can compute them):

1. Nothing present live is UNDECLARED. One declared source is not covered by the live listing: the reserve helper
   `input_number.ecco_advisory_reserve_raise_pct` (the listing's filter was names containing `ecco_intel`): `NOT_CHECKED_LIVE`; its
   Home Assistant standard attributes are unconfirmed live.
2. The three alert automations' entity ids differ from their unique ids (Home Assistant derives them from the alias): the automation
   with unique id `ecco_intel_alert_watchdog_stale` is `automation.ecco_intel_alert_no_fresh_intelligence_result` live. The catalogue
   uses the live entity id, and the unique id inside the source id.
3. While PAUSED the integration publishes once, so a paused system's rows legitimately age past `stale_after_s`; see section 9.
4. The contract-version mismatch cannot be written with the agreed alert conditions; see section 9.
5. The meaning of `{unavailable: true}` and of a mixed-type `in` list is written in section 3.1; the shell's tests should pin both
   readings.
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
- No example dashboard was written (it belongs with the shell); section 6 describes how one wraps the existing card.
- The owner's private pattern scan of `tools/tests/test_public_privacy.py` (`ECCO_PRIVATE_PATTERNS`) was not applied: the variable is
  not set and the patterns live in the offline area, which was not read.

## 11. How the proof was checked (summary)

`python -I -B -X utf8 tools/tests/test_geek_mode_catalogue.py`, `..._coverage.py`, `..._ledger.py`, `..._fixtures.py`,
`..._privacy.py`; `tools/geek_mode_coverage.py --check`; `tools/gen_geek_fixtures.py --check`; `tools/validate_repo.py`; and
`tools/run_offline_tests.py --root tools/tests --parallel 4`. The report that came with this change states the outcome of each run.
