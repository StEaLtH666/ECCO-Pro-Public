// AC15 (card side): the information coverage check, generic over ANY catalogue and states fixture. By default it runs on the mini
// fixtures; set ECCO_GEEK_CATALOGUE and ECCO_GEEK_STATES (paths) to run the very same checks on the real catalogue and fixtures
// when they are merged in, so the generated ledger and the card cannot drift: every non-excepted source has a row with the status
// the card's own rule gives it, every declared attribute path is reachable once the row is open, every discover-prefix entity that
// the catalogue does not describe appears in the Discovered group, nothing outside the prefix ever appears, and every exception of
// the catalogue is listed with its reason.
import test, { afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { installDom } from './minidom.mjs';

installDom();
const { loadCard, coverageInputs, statesFrom, makeHass, NOW } = await import('./helpers.mjs');
const { EccoModeShell, validateCatalogue, classifyRow, catalogueItemIds, buildSnapshot } = await loadCard('coverage');

const { source, catalogue, statesRaw } = coverageInputs();
const states = statesFrom(statesRaw);
const v = validateCatalogue(catalogue);
const live = new Set();
afterEach(() => {
  for (const el of live) el.disconnectedCallback();
  live.clear();
});

function mount() {
  const el = new EccoModeShell();
  live.add(el);
  el._now = () => NOW;
  el.setConfig({ type: 'custom:ecco-mode-shell', catalogue, page_size: 100, always: [], production: [] });
  el.hass = makeHass(states);
  el.connectedCallback();
  el.shadowRoot.querySelector('[data-mode-option="geek"]').click();
  return el;
}

test(`coverage (${source} inputs): the catalogue is valid`, () => {
  assert.equal(v.ok, true, JSON.stringify(v.errors));
  assert.ok(v.catalogue.sources.length > 0);
});

test(`coverage (${source} inputs): every source has one row with the status the card's rule gives it, and every declared attribute is reachable`, () => {
  const snap = buildSnapshot(states, v.catalogue, NOW);
  const el = mount();
  const root = el.shadowRoot;
  const rowFor = (eid) => root.querySelectorAll('[data-inspector-row]').find((r) => r.getAttribute('data-entity-id') === eid);
  let attributes = 0;
  for (const src of v.catalogue.sources) {
    const row = snap.rows.filter((r) => r.id === src.id);
    assert.equal(row.length, 1, `${src.id}: exactly one row`);
    assert.equal(row[0].status, classifyRow(src, states[src.entity_id], NOW).status, src.id);
    const paths = new Set(row[0].attributes.map((a) => a.path));
    for (const a of src.attributes) {
      assert.ok(paths.has(a.name), `${src.id}: ${a.name} is in the snapshot`);
      attributes += 1;
    }
    assert.ok(rowFor(src.entity_id), `${src.id}: a row in the DOM`);
    rowFor(src.entity_id).querySelector('[data-row-toggle]').click();
    for (const a of src.attributes) assert.ok(rowFor(src.entity_id).querySelector(`[data-attribute-path="${a.name}"]`), `${src.id}: ${a.name} reachable in the DOM`);
  }
  assert.equal(catalogueItemIds(v.catalogue).length, v.catalogue.sources.length + attributes, 'the ledger ids the card can show are every source and every declared attribute');
});

test(`coverage (${source} inputs): discovery finds exactly the uncatalogued prefix entities, and nothing else`, () => {
  const d = v.catalogue.discover;
  const claimed = new Set(v.catalogue.sources.map((s) => s.entity_id));
  const expected = Object.keys(states).filter((id) => !claimed.has(id) && !d.exclude_entity_ids.includes(id) && d.entity_prefixes.some((p) => id.startsWith(p))).sort();
  const snap = buildSnapshot(states, v.catalogue, NOW);
  assert.deepEqual(snap.rows.filter((r) => r.discovered).map((r) => r.entity_id).sort(), expected);
  const shown = new Set(snap.rows.map((r) => r.entity_id));
  for (const id of Object.keys(states)) {
    if (!claimed.has(id) && !expected.includes(id)) assert.ok(!shown.has(id), `${id} must never appear`);
  }
});

test(`coverage (${source} inputs): every exception is listed with its reason, so nothing is silently missing`, () => {
  const el = mount();
  const listed = el.shadowRoot.querySelectorAll('[data-exception]');
  assert.deepEqual(listed.map((e) => e.getAttribute('data-exception')), v.catalogue.exceptions.map((x) => x.id));
  assert.deepEqual(listed.map((e) => e.getAttribute('data-reason')), v.catalogue.exceptions.map((x) => x.reason));
});
