// The card against the REAL Intelligence catalogue, the machine ledger and the synthetic state fixtures written by the catalogue
// workstream (catalogue/intelligence.catalogue.json, catalogue/intelligence.ledger.json, test/fixtures/intelligence.states.*.json,
// noise.states.json). The other test files prove the card's behaviour on small hand-made fixtures; this file proves that the shell and
// the data side agree, so the ledger and the card cannot drift apart:
//   AC6   every catalogue alert fires in BOTH modes when its condition is met, and no alert goes silent when its entity is down
//   AC7   one adapter: both modes and the children follow one hass object
//   AC8   every source and every declared attribute is reachable; undeclared ecco_intel_ entities are discovered; noise never appears
//   AC9   unavailable / unknown / stale / not measured / simulated are labelled in words and an icon; nothing is invented
//   AC10  the noise decoys (and the catalogue's own redaction list) are withheld on every surface
//   AC12  a large collection stays bounded
//   AC15  the ledger and the card agree row for row (ids, attributes, honesty states, withheld values, exceptions, hashes)
import test, { afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { installDom, installResizeObserver, MElement, MEvent } from './minidom.mjs';

const { doc, win } = installDom(); // BEFORE the card module is evaluated
installResizeObserver();
const H = await import('./helpers.mjs');
const { loadCard, realCatalogue, realLedger, realCataloguePath, realLedgerPath, fixturePath, intelMeta, intelFixtureNames, intelStates, noiseStates, makeHass, tick, textOf } = H;
const mod = await loadCard('real-catalogue');
const { EccoModeShell, TAG, WITHHELD, validateCatalogue, buildSnapshot, deriveAlerts, catalogueItemIds } = mod;

class StubCard extends MElement {
  constructor() {
    super('stub-card');
    this.hassSeen = [];
  }

  setConfig(cfg) {
    this.config = cfg;
  }

  set hass(h) {
    this.hassSeen.push(h);
    this._hass = h;
    const s = h && h.states && h.states['sensor.ecco_intel_status'];
    this.textContent = s ? `child sees ${s.state}` : 'child sees nothing';
  }

  get hass() {
    return this._hass;
  }
}
doc.registerElement('stub-card', () => new StubCard());

// ---- shared fixtures ----
const CAT = realCatalogue();
const LEDGER = realLedger();
const META = intelMeta();
const NAMES = intelFixtureNames();
const VALID = validateCatalogue(CAT);

const live = new Set();
function mount({ states, now, config = {}, catalogue = realCatalogue() }) {
  win.location.pathname = '/intelligence';
  const el = new EccoModeShell();
  live.add(el);
  el._now = () => now;
  el.setConfig({ type: `custom:${TAG}`, view_id: 'intelligence', title: 'ECCO Intelligence', catalogue, page_size: 100, always: [], production: [], allow_custom_cards: ['custom:stub-card'], ...config });
  el.hass = makeHass(states);
  el.connectedCallback();
  return el;
}
afterEach(() => {
  for (const el of live) el.disconnectedCallback();
  live.clear();
});

/** A fixture by name, optionally changed by `mutate(states)`. */
function fixture(name, mutate = null) {
  const f = intelStates(name);
  if (mutate) mutate(f.states);
  return f;
}
const mountFixture = (name, mutate = null, config = {}) => {
  const f = fixture(name, mutate);
  return mount({ states: f.states, now: f.now, config });
};

const root = (el) => el.shadowRoot;
const q = (el, sel) => root(el).querySelector(sel);
const qa = (el, sel) => root(el).querySelectorAll(sel);
const geek = (el) => q(el, '[data-mode-option="geek"]').click();
const production = (el) => q(el, '[data-mode-option="production"]').click();
const rows = (el) => qa(el, '[data-inspector-row]');
const rowOf = (el, sourceId) => rows(el).find((r) => r.getAttribute('data-source-id') === sourceId);
const typeSearch = (el, text) => {
  const i = q(el, '[data-inspector-search]');
  i.value = text;
  i.dispatchEvent(new MEvent('input'));
};
const allText = (node) => {
  const parts = [];
  const walk = (n) => {
    if (n.nodeType === 3) parts.push(n.data);
    else if (n.nodeType === 1) {
      for (const [k, v] of n.attrs) parts.push(`${k}=${v}`);
      n.childNodes.forEach(walk);
    }
  };
  walk(node);
  return parts.join('\n');
};
/** Open every row (the attribute lists), then every raw view. */
function openEverything(el, { rawToo = false } = {}) {
  for (const id of rows(el).map((r) => r.getAttribute('data-source-id'))) rowOf(el, id).querySelector('[data-row-toggle]').click();
  if (rawToo) for (const t of qa(el, '[data-raw-toggle]')) t.click();
}
/** Every attribute node of every open row: { sid, path, state, declared, depth }. */
function attributeNodes(el) {
  const out = [];
  for (const r of rows(el)) {
    for (const a of r.querySelectorAll('[data-attribute-path]')) {
      out.push({ sid: r.getAttribute('data-source-id'), path: a.getAttribute('data-attribute-path'), state: a.getAttribute('data-attr-state'),
        declared: a.getAttribute('data-declared') === 'true', depth: Number(a.getAttribute('data-depth')), node: a });
    }
  }
  return out;
}
const stripOf = (el) => qa(el, '[data-ecco-alert-strip] [data-alert-id]');
const stripSnapshot = (el) => stripOf(el).map((n) => `${n.getAttribute('data-alert-id')}|${n.getAttribute('data-severity')}|${n.getAttribute('data-alert-kind')}|${textOf(n)}`);
function assertStripVisible(el) {
  const strip = q(el, '[data-ecco-alert-strip]');
  assert.ok(strip);
  for (let n = strip; n && n.nodeType === 1; n = n.parentNode) assert.equal(n.hidden, false, `${n.tagName} hides the strip`);
  assert.equal(strip.closest('[data-ecco-body]'), null, 'the strip is outside both switchable bodies');
}
function installClipboardAndDownload() {
  const clips = [];
  const blobs = [];
  const nav = Object.getOwnPropertyDescriptor(globalThis, 'navigator');
  Object.defineProperty(globalThis, 'navigator', { value: { clipboard: { writeText: async (t) => { clips.push(t); } } }, configurable: true, writable: true });
  const create = URL.createObjectURL;
  const revoke = URL.revokeObjectURL;
  URL.createObjectURL = (b) => { blobs.push(b); return 'blob:test'; };
  URL.revokeObjectURL = () => {};
  return {
    clips, blobs,
    restore() {
      if (nav) Object.defineProperty(globalThis, 'navigator', nav);
      else delete globalThis.navigator;
      URL.createObjectURL = create;
      URL.revokeObjectURL = revoke;
    },
  };
}
/** True when `id` appears as a whole entity id in `text` (sensor.ecco_intel is not found inside sensor.ecco_intel_status). */
const mentions = (text, id) => text.split(id).some((_, i, parts) => {
  if (i === 0) return false;
  const before = parts[i - 1].slice(-1);
  const after = parts[i].slice(0, 1);
  return !/[A-Za-z0-9_.]/.test(before) && !/[A-Za-z0-9_]/.test(after);
});
const sha256 = (file) => createHash('sha256').update(readFileSync(file)).digest('hex');

// ===========================================================================================================================
// the catalogue is valid for the card, and says what the ledger says
// ===========================================================================================================================
test('the real catalogue passes the card validator with no error, so no alert and no source is silently dropped', () => {
  assert.equal(VALID.ok, true, JSON.stringify(VALID.errors));
  assert.equal(VALID.catalogue.sources.length, CAT.sources.length);
  assert.equal(VALID.catalogue.alerts.length, CAT.alerts.length, 'every alert survives validation');
  assert.equal(VALID.catalogue.exceptions.length, CAT.exceptions.length);
  assert.equal(VALID.catalogue.sources.length, 17);
  assert.equal(VALID.catalogue.sources.reduce((n, s) => n + s.attributes.length, 0), 344);
  assert.equal(VALID.catalogue.alerts.length, 19, '15 status, quality and wiring alerts plus the four review-round alerts on the status entity');
});

test('every alert names a catalogued source entity, and every source has a group the catalogue defines', () => {
  const entities = new Set(CAT.sources.map((s) => s.entity_id));
  for (const a of CAT.alerts) assert.ok(entities.has(a.entity_id), `${a.id}: ${a.entity_id} is not a catalogued source`);
  const groups = new Set(CAT.groups.map((g) => g.id));
  for (const s of CAT.sources) assert.ok(groups.has(s.group), `${s.id}: group ${s.group}`);
  assert.ok(groups.has(CAT.discover.group));
});

// ===========================================================================================================================
// AC6: the readings of the alert conditions that the catalogue documents (interface 3.1), pinned
// ===========================================================================================================================
function alertsOf(name, mutate = null) {
  const f = fixture(name, mutate);
  const snap = buildSnapshot(f.states, VALID.catalogue, f.now);
  return deriveAlerts(snap, VALID.catalogue);
}
const idsOf = (alerts) => alerts.map((a) => a.id);

test('AC6 reading {attribute, in}: the in-list may mix booleans and texts, and a value matches strictly or as text', () => {
  const with_ = (v) => alertsOf('healthy', (s) => { s['sensor.ecco_intel_status'].attributes.applies_nothing = v; });
  for (const v of [false, 'false', 'False']) {
    const got = with_(v).filter((a) => a.id === 'applies_nothing_false');
    assert.equal(got.length, 1, `applies_nothing = ${JSON.stringify(v)} must raise the critical alert`);
    assert.equal(got[0].severity, 'critical');
    assert.equal(got[0].kind, 'condition');
  }
  for (const v of [true, 'true', 'True']) assert.ok(!idsOf(with_(v)).some((i) => i.startsWith('applies_nothing_false')), `applies_nothing = ${JSON.stringify(v)} is fine`);
  for (const how of [(s) => { delete s['sensor.ecco_intel_status'].attributes.applies_nothing; }, (s) => { s['sensor.ecco_intel_status'].attributes.applies_nothing = null; }]) {
    const got = alertsOf('healthy', how).filter((a) => a.id.startsWith('applies_nothing_false'));
    assert.deepEqual(got.map((a) => a.id), ['applies_nothing_false:unverifiable'], 'an absent safety flag is reported, never silent');
    assert.notEqual(got[0].severity, 'critical');
  }
});

test('AC6 reading {unavailable: true}: the state unavailable OR a missing entity fires; an unknown state does not, and is reported as a condition that cannot be checked', () => {
  const pause = 'input_boolean.ecco_intel_paused';
  assert.ok(idsOf(alertsOf('healthy', (s) => { s[pause].state = 'unavailable'; })).includes('pause_switch_unavailable'));
  assert.ok(idsOf(alertsOf('healthy', (s) => { delete s[pause]; })).includes('pause_switch_unavailable'), 'a declared entity that is missing is as bad as an unavailable one');
  const unknown = alertsOf('healthy', (s) => { s[pause].state = 'unknown'; });
  assert.ok(!idsOf(unknown).includes('pause_switch_unavailable'), 'unknown is not unavailable');
  assert.ok(idsOf(unknown).includes('pause_switch_unavailable:unverifiable'), 'but it is never silent');
  // the watchdog (the other {unavailable: true} alert)
  assert.ok(idsOf(alertsOf('healthy', (s) => { delete s['binary_sensor.ecco_intel_watchdog_fresh']; })).includes('watchdog_unavailable'));
});

test('AC6 reading {state_in}: a listed state fires even when that state is unknown or unavailable; an unlisted down state is reported as unverifiable', () => {
  const status = 'sensor.ecco_intel_status';
  const unknown = alertsOf('healthy', (s) => { s[status].state = 'unknown'; });
  assert.ok(idsOf(unknown).includes('status_unknown'), 'the unknown status fires its own info alert');
  assert.ok(!idsOf(unknown).includes('status_unavailable'), 'and not the critical not-publishing alert (a restart must not raise it)');
  assert.deepEqual(idsOf(unknown).filter((i) => i.endsWith(':unverifiable') && unknown.find((a) => a.id === i).entity_id === status), [],
    'the entity is already reported as down, so no redundant cannot-check lines for it');
  const down = alertsOf('healthy', (s) => { s[status].state = 'unavailable'; });
  assert.ok(idsOf(down).includes('status_unavailable'));
  assert.equal(down.find((a) => a.id === 'status_unavailable').severity, 'critical');
  assert.ok(!idsOf(down).includes('status_unknown'));
  const watchdogUnknown = alertsOf('healthy', (s) => { s['binary_sensor.ecco_intel_watchdog_fresh'].state = 'unknown'; });
  assert.ok(idsOf(watchdogUnknown).includes('watchdog_off:unverifiable'), 'a state that is not in the list but cannot be trusted is reported, not cleared');
});

// ===========================================================================================================================
// AC6: every catalogue alert fires in both modes when its condition is met
// ===========================================================================================================================
/** The states that meet one alert's condition, as [label, mutate] pairs (one per way the condition can hold). */
function triggers(a) {
  const id = a.entity_id;
  const w = a.when;
  if (w.unavailable === true) return [['state unavailable', (s) => { s[id].state = 'unavailable'; }], ['entity missing', (s) => { delete s[id]; }]];
  if (w.state_in) return w.state_in.map((v) => [`state ${v}`, (s) => { s[id].state = v; }]);
  if (w.state_outside) return [['an unlisted state', (s) => { s[id].state = 'zz_not_listed'; }]];
  if (w.state_not_in) return [['an unlisted state', (s) => { s[id].state = 'zz_not_listed'; }]];
  if (w.attribute && w.not_in) return [[`${w.attribute} = an unlisted value`, (s) => { s[id].attributes[w.attribute] = 'zz_not_listed'; }]];
  if (w.attribute) return w.in.map((v) => [`${w.attribute} = ${JSON.stringify(v)}`, (s) => { s[id].attributes[w.attribute] = v; }]);
  throw new Error(`unknown condition form for ${a.id}`);
}

test('AC6 every alert has at least one way to fire, and the healthy fixture fires none of them', () => {
  for (const a of CAT.alerts) assert.ok(triggers(a).length >= 1, a.id);
  const el = mountFixture('healthy');
  assert.deepEqual(stripOf(el), []);
  assert.ok(q(el, '[data-ecco-alert-strip] [data-alert-none]'));
});

for (const a of CAT.alerts) {
  for (const [label, mutate] of triggers(a)) {
    test(`AC6 ${a.id} (${a.severity}) fires when ${label}: identical in Production and Geek Mode, with its words, its action and an icon`, () => {
      const el = mountFixture('healthy', mutate);
      const inProduction = stripSnapshot(el);
      assertStripVisible(el);
      const mine = stripOf(el).filter((n) => n.getAttribute('data-alert-id') === a.id);
      assert.equal(mine.length, 1, `${a.id} is missing from the Production strip: ${inProduction.join(' ; ')}`);
      assert.equal(mine[0].getAttribute('data-severity'), a.severity);
      assert.equal(mine[0].getAttribute('data-alert-kind'), 'condition');
      assert.equal(mine[0].getAttribute('data-entity-id'), a.entity_id);
      assert.ok(textOf(mine[0]).includes(a.text), 'the alert text');
      assert.ok(textOf(mine[0]).includes(a.action), 'the what-to-do line');
      assert.ok(mine[0].querySelector('svg'), 'an icon, not colour alone');
      geek(el);
      assertStripVisible(el);
      assert.deepEqual(stripSnapshot(el), inProduction, 'identical in Geek Mode');
      production(el);
      assert.deepEqual(stripSnapshot(el), inProduction, 'and again back in Production');
      if (a.severity === 'critical') assert.equal(mine[0].getAttribute('role'), 'alert', 'a critical alert is announced as an alert');
    });
  }

  for (const how of ['unavailable', 'unknown', 'missing']) {
    test(`AC6 ${a.id}: ${a.entity_id} ${how}: the strip is never silently clear, and is identical in both modes`, () => {
      const el = mountFixture('healthy', (s) => {
        if (how === 'missing') delete s[a.entity_id];
        else s[a.entity_id].state = how;
      });
      const p = stripSnapshot(el);
      assert.ok(stripOf(el).some((n) => n.getAttribute('data-entity-id') === a.entity_id), `no alert about ${a.entity_id} (${how})`);
      geek(el);
      assert.deepEqual(stripSnapshot(el), p);
      assertStripVisible(el);
    });
  }
}

// an independent statement of the catalogue's documented reading (interface 3.1), used to derive what each fixture must raise
function documentedConditionIds(states) {
  const out = [];
  for (const a of CAT.alerts) {
    const s = states[a.entity_id];
    const w = a.when;
    let active = false;
    if (w.unavailable === true) active = !s || s.state === 'unavailable';
    else if (w.state_in) active = !!s && w.state_in.includes(s.state);
    else if (w.state_outside) active = !!s && s.state !== 'unavailable' && s.state !== 'unknown' && !w.state_outside.includes(s.state);
    else if (w.attribute && w.not_in) active = !!s && s.attributes[w.attribute] !== undefined && s.attributes[w.attribute] !== null
      && !w.not_in.some((x) => x === s.attributes[w.attribute]);
    else if (w.attribute) active = !!s && s.attributes[w.attribute] !== undefined && s.attributes[w.attribute] !== null
      && w.in.some((x) => x === s.attributes[w.attribute] || String(x) === String(s.attributes[w.attribute]));
    else throw new Error(`the documented reading of ${a.id} is not written down in this test`);
    if (active) out.push(a.id);
  }
  return out;
}
const EXPECTED_ALERTS = {
  healthy: [],
  mixed: ['data_quality_degraded'],
  stale: ['status_stale', 'watchdog_off'],
  unavailable: ['status_unavailable', 'watchdog_off'],
  'self-test-failed': ['status_self_test_failed', 'watchdog_off'],
  paused: ['status_paused'],
  'watchdog-stale': ['watchdog_off'],
  extras: [],
  'contract-breach': ['mode_not_shadow'],
};

for (const name of NAMES) {
  test(`AC6 fixture ${name}: the strip raises exactly the alerts the documented conditions give, in both modes, and every other line says it cannot be checked`, () => {
    const f = fixture(name);
    const expected = documentedConditionIds(f.states).sort();
    assert.deepEqual(expected, [...EXPECTED_ALERTS[name]].sort(), `the documented reading of ${name} and the hand-written table agree`);
    const el = mount({ states: f.states, now: f.now });
    const conditionIds = stripOf(el).filter((n) => n.getAttribute('data-alert-kind') === 'condition').map((n) => n.getAttribute('data-alert-id')).sort();
    assert.deepEqual(conditionIds, expected);
    for (const n of stripOf(el).filter((x) => x.getAttribute('data-alert-kind') !== 'condition')) {
      assert.equal(n.getAttribute('data-alert-kind'), 'unverifiable');
      assert.notEqual(n.getAttribute('data-severity'), 'critical');
      assert.match(textOf(n), /Cannot check this right now/);
    }
    const snapshot = stripSnapshot(el);
    geek(el);
    assert.deepEqual(stripSnapshot(el), snapshot);
    assertStripVisible(el);
    if (snapshot.length === 0) assert.ok(q(el, '[data-ecco-alert-strip] [data-alert-none]'));
  });
}

test('AC6 the Production summary comes from the same alert list as the strip (the most severe alert, in words)', () => {
  const el = mountFixture('self-test-failed');
  const summary = q(el, '[data-ecco-summary]');
  assert.equal(summary.getAttribute('data-level'), 'critical');
  assert.ok(textOf(summary).includes(CAT.alerts.find((a) => a.id === 'status_self_test_failed').text));
  const calm = mountFixture('healthy');
  assert.equal(q(calm, '[data-ecco-summary]').getAttribute('data-level'), 'ok');
});

// ===========================================================================================================================
// AC8: coverage of the real catalogue on every fixture
// ===========================================================================================================================
for (const name of NAMES) {
  test(`AC8 fixture ${name}: every source has one row, every declared attribute is reachable in the DOM, and the rows are the sources plus the discovered entities only`, () => {
    const f = fixture(name);
    const el = mount({ states: f.states, now: f.now });
    geek(el);
    const listed = rows(el).map((r) => r.getAttribute('data-source-id'));
    const sourceIds = CAT.sources.map((s) => s.id);
    for (const id of sourceIds) assert.equal(listed.filter((x) => x === id).length, 1, `${id}: exactly one row`);
    const discovered = rows(el).filter((r) => r.getAttribute('data-discovered') === 'true').map((r) => r.getAttribute('data-entity-id')).sort();
    const prefixes = CAT.discover.entity_prefixes;
    const claimed = new Set(CAT.sources.map((s) => s.entity_id));
    const expectedDiscovered = Object.keys(f.states).filter((id) => !claimed.has(id) && prefixes.some((p) => id.startsWith(p))).sort();
    assert.deepEqual(discovered, expectedDiscovered);
    assert.equal(listed.length, sourceIds.length + expectedDiscovered.length, 'nothing else is listed');
    openEverything(el);
    const nodes = attributeNodes(el);
    for (const s of CAT.sources) {
      const here = new Set(nodes.filter((n) => n.sid === s.id).map((n) => n.path));
      for (const a of s.attributes) assert.ok(here.has(a.name), `${s.id}#${a.name} is reachable`);
    }
    // ... and every row can be opened to its description, its attributes and its raw view
    assert.equal(qa(el, '[data-row-detail]').length, listed.length);
  });
}

test('AC8 discovery: the four new ecco_intel_ entities appear by themselves in the Discovered group, the five lookalikes never appear', () => {
  const m = META.fixtures.extras;
  const el = mountFixture('extras');
  geek(el);
  const found = rows(el).filter((r) => r.getAttribute('data-discovered') === 'true');
  assert.deepEqual(found.map((r) => r.getAttribute('data-entity-id')).sort(), [...m.must_discover].sort());
  for (const r of found) assert.equal(r.getAttribute('data-group'), CAT.discover.group);
  const text = allText(root(el));
  for (const id of m.must_not_discover) assert.ok(!mentions(text, id), `${id} must never appear`);
  // the undeclared attribute is shown, honestly marked as not declared, and it is the only undeclared top-level attribute of any catalogued row
  openEverything(el);
  const extra = attributeNodes(el).filter((n) => !n.declared && n.depth === 0 && !rowOf(el, n.sid).getAttribute('data-source-id').startsWith('discovered:'));
  assert.deepEqual(extra.map((n) => `${n.sid}:${n.path}`), ['intel.status:zz_future_attribute']);
  assert.equal(extra[0].state, 'present');
});

test('AC8 noise: 300+ unrelated entities and the decoys added to the healthy fixture change nothing: no noise row, no discovery, no extra alert', () => {
  const f = fixture('healthy');
  const noise = noiseStates();
  assert.ok(Object.keys(noise).length >= 300);
  assert.equal(Object.keys(noise).filter((id) => CAT.discover.entity_prefixes.some((p) => id.startsWith(p))).length, 0, 'no noise entity matches a discovery prefix');
  const clean = mount({ states: f.states, now: f.now });
  geek(clean);
  const alone = rows(clean).map((r) => r.getAttribute('data-source-id'));
  const el = mount({ states: { ...f.states, ...noise }, now: f.now });
  geek(el);
  assert.deepEqual(rows(el).map((r) => r.getAttribute('data-source-id')), alone);
  assert.equal(rows(el).filter((r) => r.getAttribute('data-discovered') === 'true').length, 0);
  const text = allText(root(el));
  for (const id of Object.keys(noise)) assert.ok(!mentions(text, id), `${id} must never appear`);
  assert.deepEqual(stripSnapshot(el), []);
  assert.equal(allText(root(el)).includes('SYNTHETIC-DECOY'), false);
});

test('AC8 every exception of the catalogue is listed with its reason and its note, so nothing is silently missing', () => {
  const el = mountFixture('healthy');
  geek(el);
  const listed = qa(el, '[data-exception]');
  assert.deepEqual(listed.map((e) => e.getAttribute('data-exception')), CAT.exceptions.map((x) => x.id));
  assert.deepEqual(listed.map((e) => e.getAttribute('data-reason')), CAT.exceptions.map((x) => x.reason));
  for (const [i, e] of listed.entries()) {
    assert.ok(textOf(e).includes(CAT.exceptions[i].what), `${CAT.exceptions[i].id}: what`);
    if (CAT.exceptions[i].note) assert.ok(textOf(e).includes(CAT.exceptions[i].note.slice(0, 40)), `${CAT.exceptions[i].id}: note`);
  }
});

test('AC11 grouping and search on the real catalogue: groups in catalogue order, headline first inside each group, search reaches an obscure attribute and a description', () => {
  const el = mountFixture('extras');
  geek(el);
  const list = rows(el);
  const order = new Map(CAT.groups.map((g, i) => [g.id, i]));
  const rank = { headline: 0, normal: 1, obscure: 2 };
  for (let i = 1; i < list.length; i += 1) {
    const [a, b] = [list[i - 1], list[i]];
    const ga = order.get(a.getAttribute('data-group'));
    const gb = order.get(b.getAttribute('data-group'));
    assert.ok(ga <= gb, 'groups in catalogue order');
    if (ga === gb) assert.ok(rank[a.getAttribute('data-priority')] <= rank[b.getAttribute('data-priority')], 'headline before normal before obscure in a group');
  }
  assert.equal(list[list.length - 1].getAttribute('data-group'), CAT.discover.group, 'discovered entities come last');
  typeSearch(el, 'target_soc_pct');
  assert.ok(rows(el).some((r) => r.getAttribute('data-source-id') === 'intel.charge_target'), 'an attribute name finds its source');
  typeSearch(el, 'zz_future_attribute');
  assert.deepEqual(rows(el).map((r) => r.getAttribute('data-source-id')), ['intel.status'], 'an undeclared attribute is searchable too');
  typeSearch(el, 'no such thing anywhere');
  assert.equal(rows(el).length, 0);
  assert.ok(q(el, '[data-inspector-empty]'));
});

// ===========================================================================================================================
// AC9: honesty on the real fixtures
// ===========================================================================================================================
const LABEL = { LIVE: 'Live', STALE: 'Stale', UNAVAILABLE: 'Unavailable', UNKNOWN: 'Unknown', NOT_MEASURED: 'Not measured', SIMULATED: 'Simulated', UNVERIFIED: 'Unverified' };
/** An independent statement of the status rule (README, Honest inventory). SIMULATED and UNVERIFIED depend on attributes and are checked apart. */
function expectedStatus(src, state, now) {
  if (!state) return 'NOT_MEASURED';
  if (state.state === 'unavailable') return 'UNAVAILABLE';
  if (state.state === 'unknown' || state.state === '') return 'UNKNOWN';
  const age = (now - Date.parse(state.last_updated)) / 1000;
  return src.stale_after_s && age > src.stale_after_s ? 'STALE' : 'LIVE';
}

for (const name of NAMES) {
  test(`AC9 fixture ${name}: every row says its status in words and an icon, shows no value when it has none, and is never Live when it is not`, () => {
    const f = fixture(name);
    const el = mount({ states: f.states, now: f.now });
    geek(el);
    for (const s of CAT.sources) {
      const r = rowOf(el, s.id);
      const want = expectedStatus(s, f.states[s.entity_id], f.now);
      const got = r.getAttribute('data-status');
      if (want === 'LIVE') assert.ok(['LIVE', 'SIMULATED', 'UNVERIFIED'].includes(got), `${s.id}: ${got}`);
      else assert.equal(got, want, s.id);
      const chip = r.querySelector(`[data-status-chip="${got}"]`);
      assert.ok(chip, `${s.id}: a status chip`);
      assert.ok(textOf(chip).includes(LABEL[got]), `${s.id}: the word ${LABEL[got]}`);
      assert.ok(chip.querySelector('svg'), `${s.id}: an icon, not colour alone`);
      if (got !== 'LIVE') assert.equal(r.querySelector('[data-status-chip="LIVE"]'), null, `${s.id}: not labelled Live as well`);
      const state = r.querySelector('[data-row-state]');
      if (got === 'UNAVAILABLE') assert.equal(textOf(state), 'Unavailable', `${s.id}: no value for an unavailable source`);
      if (got === 'UNKNOWN') assert.equal(textOf(state), 'Unknown', `${s.id}: no value for an unknown source`);
      if (got === 'NOT_MEASURED') assert.equal(textOf(state), 'Not measured', `${s.id}: nothing is invented`);
      if (got === 'LIVE' && s.stale_after_s === null) assert.match(textOf(r.querySelector('[data-row-age]')), /age not monitored/);
    }
  });
}

test('AC9 a result nobody refreshed: at the watchdog-stale clock every integration entity is Stale (shown for reference, never Live) and the package helpers stay Live with an unmonitored age', () => {
  const f = fixture('watchdog-stale');
  const el = mount({ states: f.states, now: f.now });
  geek(el);
  for (const s of CAT.sources) {
    const r = rowOf(el, s.id);
    if (s.stale_after_s) {
      assert.equal(r.getAttribute('data-status'), 'STALE', s.id);
      assert.ok(textOf(r.querySelector('[data-row-age]')).length > 0);
    } else assert.equal(r.getAttribute('data-status'), 'LIVE', s.id);
  }
  // the same states read 30 s after they were published are Live: the label follows the clock, not a flag in the data
  const fresh = mount({ states: f.states, now: Date.parse(intelMeta().fixtures.healthy.reference_now) });
  geek(fresh);
  assert.equal(rowOf(fresh, 'intel.status').getAttribute('data-status'), 'LIVE');
});

test('AC9 a declared entity that Home Assistant does not have is Not measured, with no invented value and every attribute Not present', () => {
  const el = mountFixture('healthy', (s) => { delete s['sensor.ecco_intel_pv_tomorrow']; });
  geek(el);
  const r = rowOf(el, 'intel.pv_tomorrow');
  assert.equal(r.getAttribute('data-status'), 'NOT_MEASURED');
  assert.equal(textOf(r.querySelector('[data-row-state]')), 'Not measured');
  openEverything(el);
  const nodes = attributeNodes(el).filter((n) => n.sid === 'intel.pv_tomorrow');
  assert.equal(nodes.length, CAT.sources.find((s) => s.id === 'intel.pv_tomorrow').attributes.length, 'one row per declared attribute, none invented');
  assert.ok(nodes.every((n) => n.state === 'absent' && n.node.textContent.includes('Not present')), 'every attribute is honestly absent');
  assert.equal(rowOf(el, 'intel.pv_tomorrow').querySelector('[data-raw-toggle]'), null, 'there is no raw view of nothing');
});

test('AC9 simulated: the entity that carries a simulated flag is labelled Simulated in words and an icon; nothing else in the extras fixture is', () => {
  const f = fixture('extras');
  const flagged = Object.entries(f.states).filter(([, s]) => s.attributes.simulated === true).map(([id]) => id);
  assert.equal(flagged.length, 1);
  const el = mount({ states: f.states, now: f.now });
  geek(el);
  const sim = rows(el).filter((r) => r.getAttribute('data-status') === 'SIMULATED');
  assert.deepEqual(sim.map((r) => r.getAttribute('data-entity-id')), flagged);
  assert.ok(textOf(sim[0].querySelector('[data-status-chip="SIMULATED"]')).includes('Simulated'));
  assert.ok(sim[0].querySelector('[data-status-chip="SIMULATED"] svg'));
  assert.equal(sim[0].querySelector('[data-status-chip="LIVE"]'), null);
  // the header counts are the snapshot's counts, and add up
  const counts = new Map(qa(el, '[data-count-status]').map((c) => [c.getAttribute('data-count-status'), Number(c.getAttribute('data-count'))]));
  assert.equal(counts.get('SIMULATED'), 1);
});

test('AC9 the unavailable fixture: the integration is down, every integration row says so and shows no figure, and the strip says so in both modes', () => {
  const f = fixture('unavailable');
  const el = mount({ states: f.states, now: f.now });
  geek(el);
  const down = CAT.sources.filter((s) => f.states[s.entity_id] && f.states[s.entity_id].state === 'unavailable');
  assert.ok(down.length >= 11);
  for (const s of down) assert.equal(textOf(rowOf(el, s.id).querySelector('[data-row-state]')), 'Unavailable');
  assert.ok(stripOf(el).some((n) => n.getAttribute('data-alert-id') === 'status_unavailable' && n.getAttribute('data-severity') === 'critical'));
});

// ===========================================================================================================================
// AC10: redaction on every surface, against the noise decoys and against the catalogue's own list
// ===========================================================================================================================
function decoyForbidden(noise) {
  const out = new Set(JSON.stringify(noise).match(/SYNTHETIC-DECOY-\d{4}[\w-]*/g));
  for (const v of ['eyJhbGciOiJub25lIn0.eyJzeW50aGV0aWMiOjF9.c2lnbmF0dXJl', '0123456789abcdef'.repeat(4), 'fedcba9876543210'.repeat(4),
    'U1lOVEhFVElDLURFQ09ZLVBBWUxPQUQtMDAwOS1ub3QtYS1yZWFsLXNlY3JldC12YWx1ZS1hdC1hbGw=', '203.0.113.7', 'synthetic:decoy@', 'Synthetic Test Lab', '1.2345', '5.4321',
    'hooks.example.invalid/api/webhook']) out.add(v);
  return [...out];
}
/** The real catalogue with discovery pointed at the decoys, so that the card is made to show them. */
function decoyCatalogue() {
  const c = realCatalogue();
  c.discover.entity_prefixes = ['sensor.synthetic_decoy_', 'device_tracker.synthetic_decoy_'];
  return c;
}

test('AC10 the decoys: every secret-looking value of the noise fixture is withheld in rows, attributes, raw views, search, copy and export', async () => {
  const noise = noiseStates();
  const forbidden = decoyForbidden(noise);
  assert.ok(forbidden.length >= 20);
  const clip = installClipboardAndDownload();
  try {
    const now = Date.parse(META.fixtures.healthy.reference_now);
    const el = mount({ states: noise, now, catalogue: decoyCatalogue() });
    geek(el);
    const decoyIds = Object.keys(noise).filter((id) => id.includes('synthetic_decoy'));
    assert.equal(decoyIds.length, 11);
    const shown = rows(el).filter((r) => r.getAttribute('data-discovered') === 'true').map((r) => r.getAttribute('data-entity-id')).sort();
    assert.deepEqual(shown, decoyIds.sort(), 'the card was made to show every decoy');
    openEverything(el, { rawToo: true });
    assert.ok(qa(el, '[data-inspector-raw]').length >= 11, 'a raw view for every decoy');
    const text = allText(root(el));
    for (const f of forbidden) assert.ok(!text.includes(f), `the rendered view leaks ${f.slice(0, 16)}`);
    assert.ok(qa(el, '[data-withheld]').length >= 10, 'the withheld marker is shown (in words and an icon)');
    assert.ok(text.includes('visible'), 'a benign nested value is still shown in the raw view');
    // key NAMES that look secret are replaced too
    assert.ok(/withheld key/.test(text));
    // search
    for (const f of forbidden) {
      typeSearch(el, f);
      assert.equal(rows(el).length, 0, `searching for ${f.slice(0, 16)} found a row`);
    }
    typeSearch(el, '');
    // copy (all rows, then each row) and both exports
    q(el, '[data-inspector-copy]').click();
    await tick();
    for (const t of qa(el, '[data-inspector-copy="row"]')) t.click();
    await tick();
    q(el, '[data-inspector-export="json"]').click();
    q(el, '[data-inspector-export="csv"]').click();
    assert.ok(clip.clips.length >= 2 && clip.blobs.length === 2, 'copy and both exports ran');
    const outputs = [...clip.clips, ...(await Promise.all(clip.blobs.map((b) => b.text())))];
    for (const bytes of outputs) {
      assert.ok(bytes.length > 50);
      for (const f of forbidden) assert.ok(!bytes.includes(f), `an output leaks ${f.slice(0, 16)}`);
    }
    assert.match(outputs[outputs.length - 2], /ecco-geek-export\/1/);
    // and the header says how many values were held back
    assert.ok(Number(q(el, '[data-count-withheld]').getAttribute('data-count')) >= 10);
  } finally {
    clip.restore();
  }
});

test('AC10 the catalogue\'s own redaction list: the integration\'s git revision and configuration hash exist, have a row, and their values are withheld everywhere', async () => {
  const f = fixture('healthy');
  const status = f.states['sensor.ecco_intel_status'].attributes;
  assert.equal(typeof status.config_hash, 'string');
  const values = [status.config_hash, status.git_sha].filter((v) => typeof v === 'string' && v.length >= 7);
  assert.ok(values.includes('fixture00000hash'));
  const clip = installClipboardAndDownload();
  try {
    const el = mount({ states: f.states, now: f.now });
    geek(el);
    openEverything(el, { rawToo: true });
    const nodes = attributeNodes(el).filter((n) => n.sid === 'intel.status' && ['git_sha', 'config_hash'].includes(n.path));
    assert.equal(nodes.length, 2, 'both rows exist');
    for (const n of nodes) assert.ok(n.node.querySelector('[data-withheld]'), `${n.path} is marked withheld`);
    typeSearch(el, 'fixture00000hash');
    assert.equal(rows(el).length, 0);
    typeSearch(el, '');
    q(el, '[data-inspector-copy]').click();
    await tick();
    q(el, '[data-inspector-export="json"]').click();
    q(el, '[data-inspector-export="csv"]').click();
    const outputs = [allText(root(el)), ...clip.clips, ...(await Promise.all(clip.blobs.map((b) => b.text())))];
    for (const bytes of outputs) assert.ok(!bytes.includes('fixture00000hash'), 'the configuration hash leaked');
  } finally {
    clip.restore();
  }
});

// ===========================================================================================================================
// AC7: one adapter feeds both modes and the children
// ===========================================================================================================================
test('AC7 one hass object feeds the strip, the Production summary, the Geek rows and the child cards; a change reaches all of them and nothing else is read', () => {
  const healthy = fixture('healthy');
  const el = mount({ states: healthy.states, now: healthy.now, config: { always: [{ type: 'custom:stub-card' }], production: [{ type: 'custom:stub-card' }] } });
  const kids = qa(el, 'stub-card');
  assert.equal(kids.length, 2);
  assert.deepEqual(stripSnapshot(el), []);
  geek(el);
  assert.equal(rowOf(el, 'intel.status').getAttribute('data-status'), 'LIVE');
  const next = makeHass(fixture('stale').states);
  el.hass = next;
  for (const k of kids) assert.equal(k.hass, next, 'the very same hass object reaches every child');
  assert.ok(textOf(kids[0]).includes('child sees STALE'));
  assert.ok(stripOf(el).some((n) => n.getAttribute('data-alert-id') === 'status_stale'), 'the strip followed');
  assert.equal(textOf(rowOf(el, 'intel.status').querySelector('[data-row-state]')), 'STALE', 'the Geek row followed');
  production(el);
  assert.ok(textOf(q(el, '[data-ecco-summary]')).includes(CAT.alerts.find((a) => a.id === 'status_stale').text), 'the Production summary followed');
  assert.equal(q(el, '[data-ecco-summary]').getAttribute('data-level'), 'attention');
  // the same snapshot rule both ways: the rows the Geek view lists are what buildSnapshot says
  geek(el);
  const snap = buildSnapshot(next.states, VALID.catalogue, healthy.now);
  assert.deepEqual(rows(el).map((r) => r.getAttribute('data-source-id')), snap.rows.map((r) => r.id));
});

// ===========================================================================================================================
// AC12: a large collection stays bounded on the real catalogue
// ===========================================================================================================================
test('AC12 the real catalogue with 5000 extra ecco_intel_ entities: one page in the DOM, a quick search, one changed entity rebuilds one row', () => {
  const f = fixture('healthy');
  const states = { ...f.states };
  const stamp = f.states['sensor.ecco_intel_status'].last_updated;
  for (let i = 0; i < 5000; i += 1) {
    const id = `sensor.ecco_intel_gen_${String(i).padStart(5, '0')}`;
    states[id] = { entity_id: id, state: String(i), attributes: { friendly_name: `Generated ${i}`, unit_of_measurement: 'kWh', detail: { a: i, b: 'text' } }, last_changed: stamp, last_updated: stamp };
  }
  const el = mount({ states, now: f.now, config: { page_size: 25 } });
  let t = performance.now();
  geek(el);
  const first = performance.now() - t;
  assert.ok(first < 8000, `first Geek render ${first.toFixed(0)} ms`);
  assert.ok(rows(el).length <= 25, `${rows(el).length} rows in the DOM`);
  assert.ok(el.inspectorStats.rowBuilds <= 25);
  assert.match(textOf(q(el, '[data-inspector-page-info]')), /of 5017/);
  t = performance.now();
  typeSearch(el, 'generated 4999');
  const search = performance.now() - t;
  assert.equal(rows(el).length, 1);
  assert.ok(search < 1500, `search ${search.toFixed(0)} ms`);
  typeSearch(el, '');
  const target = rows(el)[0].getAttribute('data-entity-id');
  const before = el.inspectorStats.rowBuilds;
  el.hass = makeHass({ ...states, [target]: { ...states[target], state: 'changed!', attributes: { ...states[target].attributes }, last_updated: stamp } });
  assert.equal(el.inspectorStats.rowBuilds - before, 1, 'exactly one row was rebuilt');
});

// ===========================================================================================================================
// AC15: the machine ledger and the card agree, row for row
// ===========================================================================================================================
test('AC15 the ledger is bound to these very files: the catalogue, the live shape and every fixture have the hash the ledger recorded', () => {
  assert.equal(sha256(realCataloguePath), LEDGER.catalogue_sha256);
  assert.equal(sha256(`${realCataloguePath.replace('intelligence.catalogue.json', 'live-shape.intelligence.json')}`), LEDGER.live_shape_sha256);
  for (const [name, hash] of Object.entries(LEDGER.fixtures_sha256)) {
    const file = name === 'noise' ? 'noise.states.json' : META.fixtures[name].file;
    assert.equal(sha256(fixturePath(file)), hash, `fixture ${name}`);
  }
  assert.deepEqual(Object.keys(LEDGER.fixtures_sha256).filter((n) => n !== 'noise').sort(), [...NAMES].sort(), 'the ledger knows every fixture');
  assert.equal(LEDGER.view_id, CAT.view_id);
  assert.equal(LEDGER.contract, CAT.contract);
});

test('AC15 the ids the card can show are exactly the ledger rows: every COVERED row is a card item, every card item has a ledger row', () => {
  const card = catalogueItemIds(VALID.catalogue);
  const ledger = LEDGER.rows.map((r) => r.id);
  assert.equal(new Set(ledger).size, ledger.length, 'ledger ids are unique');
  assert.equal(new Set(card).size, card.length);
  assert.deepEqual([...card].sort(), [...ledger].sort());
  assert.equal(ledger.length, 361);
  assert.deepEqual(LEDGER.vocabulary.coverage, ['COVERED', 'EXCEPTION']);
  for (const r of LEDGER.rows) assert.equal(r.coverage, 'COVERED', `${r.id}: every row of the ledger is covered`);
  assert.equal(LEDGER.totals.covered, ledger.length);
  assert.equal(LEDGER.totals.sources, CAT.sources.length);
  assert.equal(LEDGER.totals.attributes, CAT.sources.reduce((n, s) => n + s.attributes.length, 0));
});

test('AC15 the ledger rows carry the catalogue\'s group, priority, origin and entity; the ledger kind matches the id rule', () => {
  const sources = new Map(CAT.sources.map((s) => [s.id, s]));
  for (const r of LEDGER.rows) {
    const sid = r.id.split('#')[0];
    const s = sources.get(sid);
    assert.ok(s, `${r.id}: a catalogue source`);
    assert.equal(r.entity_id, s.entity_id);
    assert.equal(r.group, s.group);
    assert.equal(r.origin, s.origin);
    if (r.kind === 'source') {
      assert.equal(r.id, sid);
      assert.equal(r.path, null);
      assert.equal(r.priority, s.priority);
    } else {
      assert.equal(r.kind, 'attribute');
      const a = s.attributes.find((x) => x.name === r.path);
      assert.ok(a, `${r.id}: a declared attribute`);
      assert.equal(r.id, `${sid}#${a.name}`);
      assert.equal(r.priority, a.priority);
    }
  }
});

test('AC15 on every fixture the card renders each ledger row: the source row, and for each attribute a node that is present exactly when the ledger says the fixture shows it', () => {
  const byId = new Map(LEDGER.rows.map((r) => [r.id, r]));
  for (const name of NAMES) {
    const f = fixture(name);
    const el = mount({ states: f.states, now: f.now });
    geek(el);
    openEverything(el);
    const nodes = attributeNodes(el);
    const have = new Map(nodes.filter((n) => n.declared).map((n) => [`${n.sid}#${n.path}`, n]));
    for (const r of LEDGER.rows) {
      if (r.kind === 'source') {
        assert.ok(rowOf(el, r.id), `${name}: ${r.id} has a card row`);
        continue;
      }
      const node = have.get(r.id);
      assert.ok(node, `${name}: ${r.id} has a card attribute row`);
      assert.ok(node.declared, `${name}: ${r.id} is a declared row`);
      const seen = (r.seen_in || []).includes(name);
      assert.equal(node.state !== 'absent', seen, `${name}: ${r.id} is ${node.state} but the ledger says seen_in=${JSON.stringify(r.seen_in)}`);
    }
    // for every card row there is a ledger row
    for (const id of rows(el).map((r) => r.getAttribute('data-source-id')).filter((x) => !x.startsWith('discovered:'))) assert.ok(byId.has(id), `${name}: card row ${id} has no ledger row`);
    for (const [id, n] of have) assert.ok(byId.has(id), `${name}: card attribute ${id} has no ledger row (${n.state})`);
  }
});

test('AC15 an undeclared attribute is never hidden: outside the extras fixture every top-level attribute the card lists has a ledger row, and undeclared sub-keys sit under a ledger row', () => {
  const ids = new Set(LEDGER.rows.map((r) => r.id));
  const undeclaredSubKeys = new Map();
  for (const name of NAMES) {
    const f = fixture(name);
    const el = mount({ states: f.states, now: f.now });
    geek(el);
    openEverything(el);
    for (const n of attributeNodes(el)) {
      if (n.sid.startsWith('discovered:')) continue;
      const id = `${n.sid}#${n.path}`;
      if (ids.has(id)) continue;
      assert.equal(n.declared, false);
      if (n.depth === 0) {
        assert.equal(name, 'extras', `${name}: top-level attribute ${id} has no ledger row`);
        assert.equal(n.path, 'zz_future_attribute');
      } else {
        const parent = n.path.split('.')[0];
        assert.ok(ids.has(`${n.sid}#${parent}`), `${name}: ${id} sits under no ledger row`);
        undeclaredSubKeys.set(`${n.sid}#${parent}`, (undeclaredSubKeys.get(`${n.sid}#${parent}`) || 0) + 1);
      }
    }
  }
  // the keys of a dict attribute are data, listed under their parent (the ledger documents this for self_test); name every parent so a new one is noticed
  assert.deepEqual([...undeclaredSubKeys.keys()].sort(), ['intel.status#self_test']);
});

test('AC15 honesty vocabulary: on every fixture each source row\'s status is one the ledger says that row can take', () => {
  const byId = new Map(LEDGER.rows.map((r) => [r.id, r]));
  for (const name of NAMES) {
    const f = fixture(name);
    const el = mount({ states: f.states, now: f.now });
    geek(el);
    for (const s of CAT.sources) {
      const status = rowOf(el, s.id).getAttribute('data-status');
      assert.ok(byId.get(s.id).honesty.includes(status), `${name}: ${s.id} is ${status}, the ledger allows ${byId.get(s.id).honesty.join(',')}`);
      assert.ok(LEDGER.vocabulary.honesty.includes(status));
    }
  }
});

test('AC15 withheld values: the ledger rows whose value is withheld are exactly the attribute rows the card shows withheld', () => {
  const f = fixture('healthy');
  const el = mount({ states: f.states, now: f.now });
  geek(el);
  openEverything(el);
  const shown = attributeNodes(el).filter((n) => n.declared && n.node.querySelector('[data-withheld]')).map((n) => `${n.sid}#${n.path}`).sort();
  const policy = LEDGER.rows.filter((r) => r.value_policy === 'withheld').map((r) => r.id).sort();
  assert.deepEqual(shown, policy);
  assert.equal(policy.length, LEDGER.totals.attributes_withheld_by_redaction);
  assert.deepEqual(policy, ['intel.status#config_hash', 'intel.status#git_sha']);
});

test('AC15 exceptions: the ledger, the catalogue and the card list the same ones, each with a reason from the agreed list and a note saying what showing it would take', () => {
  const key = (x) => `${x.id}|${x.reason}`;
  assert.deepEqual(LEDGER.exceptions.map(key), CAT.exceptions.map(key));
  const reasons = new Set(LEDGER.vocabulary.exception_reasons);
  const counts = {};
  for (const x of CAT.exceptions) {
    assert.ok(reasons.has(x.reason), `${x.id}: ${x.reason}`);
    assert.ok(x.what.length > 3 && x.note.length > 20, `${x.id}: justified`);
    counts[x.reason] = (counts[x.reason] || 0) + 1;
  }
  for (const r of reasons) assert.equal(LEDGER.totals.exceptions_by_reason[r], counts[r] || 0, r);
  assert.equal(LEDGER.totals.exceptions, CAT.exceptions.length);
  const el = mountFixture('healthy');
  geek(el);
  assert.deepEqual(qa(el, '[data-exception]').map((e) => `${e.getAttribute('data-exception')}|${e.getAttribute('data-reason')}`), CAT.exceptions.map(key));
});

test('AC15 the live comparison: nothing present live is undeclared; the not-present-live attributes are all declared and all conditional', () => {
  assert.deepEqual(LEDGER.live.undeclared, []);
  assert.equal(LEDGER.totals.live.UNDECLARED, 0);
  const ids = new Set(LEDGER.rows.map((r) => r.id));
  for (const n of LEDGER.live.not_present_live) {
    const src = CAT.sources.find((s) => s.entity_id === n.entity_id);
    assert.ok(src && ids.has(`${src.id}#${n.path}`), `${n.entity_id} ${n.path}`);
    assert.match(n.why, /^conditional/);
  }
  assert.equal(LEDGER.live.not_present_live.length, LEDGER.totals.live.NOT_PRESENT_LIVE);
  assert.equal(LEDGER.rows.filter((r) => r.live === 'NOT_PRESENT_LIVE').length, LEDGER.totals.live.NOT_PRESENT_LIVE);
  assert.equal(LEDGER.rows.filter((r) => r.live === 'NOT_CHECKED_LIVE').length, LEDGER.totals.live.NOT_CHECKED_LIVE);
});

// the files named in the report exist where the README says
test('the ledger and the catalogue files are the ones the README and the example name', () => {
  assert.ok(readFileSync(realLedgerPath, 'utf8').includes('ecco-geek-ledger/1'));
  assert.ok(readFileSync(realCataloguePath, 'utf8').includes('ecco-geek-catalogue/1'));
});

// ===========================================================================================================================
// Review round 1 ([r1]): the safety facts the package watchdog depends on are alerted by the status entity ITSELF
// ===========================================================================================================================
// In a real Home Assistant the package watchdog template turns OFF when the status says a mode other than SHADOW, applies_nothing is not
// strictly true, the contract is not ecco-intel-entities/1, or the status word is not one of the contract's. The offline fixtures did not
// model that coupling: with the watchdog still ON the strip said "No active alerts" and the Production summary said everything looked normal.
const ST = 'sensor.ecco_intel_status';
const WD = 'binary_sensor.ecco_intel_watchdog_fresh';
const conditionIdsOf = (el) => stripOf(el).filter((n) => n.getAttribute('data-alert-kind') === 'condition')
  .map((n) => `${n.getAttribute('data-severity')}:${n.getAttribute('data-alert-id')}`).sort();
const setAttr = (name, value) => (s) => { s[ST].attributes[name] = value; };
const setState = (value) => (s) => { s[ST].state = value; };

const COUPLING = [
  ['mode ASSISTED', setAttr('mode', 'ASSISTED'), ['critical:mode_not_shadow']],
  ['mode AUTONOMOUS', setAttr('mode', 'AUTONOMOUS'), ['critical:mode_not_shadow']],
  ['mode shadow in lower case', setAttr('mode', 'shadow'), ['critical:mode_not_shadow']],
  ['mode an empty text', setAttr('mode', ''), ['critical:mode_not_shadow']],
  ['applies_nothing 0', setAttr('applies_nothing', 0), ['critical:applies_nothing_not_true']],
  ['applies_nothing the text no', setAttr('applies_nothing', 'no'), ['critical:applies_nothing_not_true']],
  ['applies_nothing the text true (the watchdog needs the boolean)', setAttr('applies_nothing', 'true'), ['critical:applies_nothing_not_true']],
  ['applies_nothing the text True', setAttr('applies_nothing', 'True'), ['critical:applies_nothing_not_true']],
  ['applies_nothing an empty text', setAttr('applies_nothing', ''), ['critical:applies_nothing_not_true']],
  ['applies_nothing false (one line, not two)', setAttr('applies_nothing', false), ['critical:applies_nothing_false']],
  ['applies_nothing the text false (one line, not two)', setAttr('applies_nothing', 'false'), ['critical:applies_nothing_false']],
  ['applies_nothing the text False (one line, not two)', setAttr('applies_nothing', 'False'), ['critical:applies_nothing_false']],
  ['contract version 2', setAttr('contract_version', 'ecco-intel-entities/2'), ['critical:contract_mismatch']],
  ['contract version an empty text', setAttr('contract_version', ''), ['critical:contract_mismatch']],
  ['an unknown status word', setState('WEIRD'), ['warning:status_unrecognised']],
  ['a status word in lower case', setState('ok'), ['warning:status_unrecognised']],
  ['mode and contract both wrong', (s) => { setAttr('mode', 'ASSISTED')(s); setAttr('contract_version', 'x/9')(s); }, ['critical:contract_mismatch', 'critical:mode_not_shadow']],
];

for (const [label, mutate, expected] of COUPLING) {
  test(`AC6 [r1] ${label}: with the watchdog still ON the strip says so in both modes (${expected.join(', ')})`, () => {
    const f = fixture('healthy', mutate);
    assert.equal(f.states[WD].state, 'on', 'the coupling case: the watchdog is still on in this fixture');
    const el = mount({ states: f.states, now: f.now });
    assert.deepEqual(conditionIdsOf(el), [...expected].sort());
    const inProduction = stripSnapshot(el);
    for (const id of expected) {
      const node = stripOf(el).find((n) => `${n.getAttribute('data-severity')}:${n.getAttribute('data-alert-id')}` === id);
      assert.ok(node.querySelector('svg'), 'an icon, not colour alone');
      assert.match(textOf(node), /What to do:/);
      if (id.startsWith('critical')) assert.equal(node.getAttribute('role'), 'alert');
    }
    const level = q(el, '[data-ecco-summary]').getAttribute('data-level');
    assert.equal(level, expected.some((e) => e.startsWith('critical')) ? 'critical' : 'attention', 'the Production summary does not say everything looks normal');
    assert.doesNotMatch(textOf(q(el, '[data-ecco-summary]')), /looks normal/);
    geek(el);
    assertStripVisible(el);
    assert.deepEqual(stripSnapshot(el), inProduction);
    production(el);
    assert.deepEqual(stripSnapshot(el), inProduction);
  });
}

test('AC6 [r1] the contract-breach fixture: the status is OK and the watchdog is on, yet the status says ASSISTED: a critical line names it in both modes', () => {
  const f = fixture('contract-breach');
  assert.equal(f.states[ST].state, 'OK');
  assert.equal(f.states[WD].state, 'on');
  assert.equal(f.states[ST].attributes.mode, 'ASSISTED');
  const el = mount({ states: f.states, now: f.now });
  assert.deepEqual(conditionIdsOf(el), ['critical:mode_not_shadow']);
  const p = stripSnapshot(el);
  geek(el);
  assert.deepEqual(stripSnapshot(el), p);
  assertStripVisible(el);
  assert.equal(q(el, '[data-ecco-summary]').getAttribute('data-level'), 'critical');
});

test('AC6 [r1] the four review-round alerts are in the catalogue with the right severity, on the status entity, and the strict applies_nothing line never doubles the existing one', () => {
  const by = Object.fromEntries(CAT.alerts.map((a) => [a.id, a]));
  for (const [id, sev] of [['mode_not_shadow', 'critical'], ['applies_nothing_not_true', 'critical'], ['contract_mismatch', 'critical'], ['status_unrecognised', 'warning']]) {
    assert.ok(by[id], id);
    assert.equal(by[id].severity, sev, id);
    assert.equal(by[id].entity_id, ST, id);
  }
  assert.deepEqual(by.mode_not_shadow.when, { attribute: 'mode', not_in: ['SHADOW'] });
  assert.deepEqual(by.contract_mismatch.when, { attribute: 'contract_version', not_in: [CAT.contract] });
  assert.deepEqual(by.status_unrecognised.when.state_outside.slice().sort(), ['BLOCKED', 'INSUFFICIENT_DATA', 'NO_ADVICE', 'OK', 'PAUSED', 'SELF_TEST_FAILED', 'STALE', 'STARTING']);
  // the two applies_nothing alerts partition the values: no value fires both, and only boolean true fires neither
  const both = [true, false, 'true', 'false', 'True', 'False', 0, 1, 'no', '', null].filter((v) => {
    const ids = alertsOf('healthy', setAttr('applies_nothing', v)).map((a) => a.id);
    return ids.includes('applies_nothing_false') && ids.includes('applies_nothing_not_true');
  });
  assert.deepEqual(both, []);
  const neither = [true, false, 'true', 'false', 'True', 'False', 0, 1, 'no', ''].filter((v) => {
    const ids = alertsOf('healthy', setAttr('applies_nothing', v)).map((a) => a.id);
    return !ids.includes('applies_nothing_false') && !ids.includes('applies_nothing_not_true');
  });
  assert.deepEqual(neither, [true], 'only the boolean true raises neither');
});

test('AC6 [r1] with the status entity unavailable, unknown or missing the four new lines add nothing: the one line that says the integration is down stays alone', () => {
  for (const how of ['unavailable', 'unknown', 'missing']) {
    const f = fixture('healthy', (s) => { if (how === 'missing') delete s[ST]; else s[ST].state = how; });
    const el = mount({ states: f.states, now: f.now });
    const ids = stripOf(el).map((n) => n.getAttribute('data-alert-id'));
    for (const id of ['mode_not_shadow', 'applies_nothing_not_true', 'contract_mismatch', 'status_unrecognised']) {
      assert.ok(!ids.includes(id) && !ids.includes(`${id}:unverifiable`), `${id} (${how}): ${ids.join(', ')}`);
    }
  }
});

// ---------------------------------------------------------------------------------------------------------------------------
// Review round 7 ([r7]): the scan budget (LIMITS.entityChars) against the REAL data. The budget exists to bound a hostile or odd entity; it must never touch an honest one. The largest real Intelligence entity
// (from the live shape listing: the encoded size of every attribute, and the length of every name) is a small part of it, and every synthetic fixture is read whole.
// ---------------------------------------------------------------------------------------------------------------------------
test('AC12 [r7] the scan budget has room: the largest real Intelligence entity (names and encoded values, from the live shape listing) is at most a twentieth of LIMITS.entityChars, and so is the whole listing of sixteen entities', () => {
  const shapePath = realCataloguePath.replace('intelligence.catalogue.json', 'live-shape.intelligence.json');
  const shape = JSON.parse(readFileSync(shapePath, 'utf8'));
  const sizes = shape.ecco_intel.map((e) => [e.entity_id, (e.state_len || 0) + Object.entries(e.attributes || {}).reduce((n, [k, v]) => n + k.length + (v.bytes || 0), 0)]);
  assert.ok(sizes.length >= 10, `${sizes.length} real entities`);
  const [biggestId, biggest] = sizes.sort((a, b) => b[1] - a[1])[0];
  assert.ok(biggest * 20 <= mod.LIMITS.entityChars, `${biggestId} is ${biggest} characters of names and values; the budget is ${mod.LIMITS.entityChars}`);
  assert.ok(sizes.reduce((n, [, s]) => n + s, 0) * 5 <= mod.LIMITS.entityChars * 3, 'the whole listing is within a few entities of budget, and each entity has a budget of its own');
});

test('AC12 [r7] every Intelligence fixture is read whole by the budget: no row has an attribute row that says values were not read, and no value is withheld that the redaction rules alone would not withhold (the same snapshot with the budget made unreachable gives the same withheld counts)', () => {
  const cat = validateCatalogue(realCatalogue()).catalogue;
  for (const name of intelFixtureNames()) {
    const f = intelStates(name);
    const snap = buildSnapshot(f.states, cat, f.now);
    for (const r of snap.rows) assert.equal(r.attributes.some((a) => a.name.includes('values not read')), false, `${name}: ${r.entity_id}`);
    assert.ok(snap.rows.length >= 16, `${name}: ${snap.rows.length} rows`);
    // each entity redacted with a budget of its own, each one with a budget a hundred times the size: the withheld counts are the same
    for (const r of snap.rows) {
      const st = f.states[r.entity_id];
      if (!st) continue;
      const wide = mod.redactAttributes(st.attributes || {}, { extraKeyPatterns: cat.redaction.extra_key_patterns, scan: { left: 100 * mod.LIMITS.entityChars } });
      assert.deepEqual(r.redacted, wide, `${name}: ${r.entity_id}`);
    }
  }
});
