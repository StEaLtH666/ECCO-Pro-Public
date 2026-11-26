// The custom element against the minidom stand-in: registration, reading hass.states only, no write path, re-render
// discipline, the timer's lifecycle.
import test, { mock, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { installDom } from './minidom.mjs';

const registry = installDom(); // BEFORE the card module is evaluated
const mod = await import('../ecco-intelligence-card.js?element');
const { statesFor, nowFor, ids } = await import('./helpers.mjs');
const { EccoIntelligenceCard, TAG } = mod;

const live = new Set();
function make(config = {}) {
  const el = new EccoIntelligenceCard();
  live.add(el);
  el.setConfig(config);
  return el;
}
afterEach(() => {
  for (const el of live) el.disconnectedCallback();
  live.clear();
});

/** A hass object that records every property read; only `states` may be read, and nothing may be called. */
function spyHass(states) {
  const reads = [];
  const calls = [];
  const trap = (name) => (...args) => { calls.push([name, args]); return Promise.resolve(); };
  const target = {
    states, callService: trap('callService'), callWS: trap('callWS'), callApi: trap('callApi'),
    connection: new Proxy({}, { get: (_t, p) => { reads.push(`connection.${String(p)}`); return trap(`connection.${String(p)}`); } }),
    user: { is_admin: true }, themes: { darkMode: true }, language: 'en',
  };
  const hass = new Proxy(target, { get: (t, p) => { reads.push(String(p)); return t[p]; } });
  return { hass, reads, calls };
}

test('registration: the element is defined once and the card picker entry is pushed once', async () => {
  assert.equal(registry.get(TAG), EccoIntelligenceCard);
  await import('../ecco-intelligence-card.js?again');
  assert.equal(registry.get(TAG), EccoIntelligenceCard, 'a second evaluation does not redefine the tag');
  assert.equal(window.customCards.filter((c) => c.type === TAG).length, 1);
  assert.equal(window.customCards[0].preview, false);
  assert.deepEqual(EccoIntelligenceCard.getStubConfig(), { type: `custom:${TAG}` });
});

test('render: setConfig + hass render the card into the shadow root', () => {
  const el = make();
  el._now = () => nowFor('synthetic_ok');
  const { hass } = spyHass(statesFor('synthetic_ok'));
  el.hass = hass;
  const root = el.shadowRoot;
  assert.ok(root.querySelector('style'));
  assert.equal(root.querySelector('ha-card').getAttribute('data-kind'), 'live');
  assert.equal(root.querySelector('[data-fig="charge_target"]').textContent, '80%');
  assert.equal(el.getCardSize(), 9);
  assert.deepEqual(el.getGridOptions(), { columns: 'full', rows: 'auto', min_columns: 6 });
});

test('no write path: across every fixture the card reads hass.states only and calls nothing', () => {
  for (const name of ['all_open_blocked', 'synthetic_ok', 'stale', 'paused', 'self_test_failed', 'starting']) {
    const el = make();
    el._now = () => nowFor(name);
    const { hass, reads, calls } = spyHass(statesFor(name));
    el.hass = hass;
    el.connectedCallback();
    el._render();
    assert.deepEqual([...new Set(reads)], ['states'], name);
    assert.deepEqual(calls, [], name);
  }
});

test('re-render discipline: an unchanged hass does not re-render; a changed state does', () => {
  const el = make();
  el._now = () => nowFor('synthetic_ok');
  const s = statesFor('synthetic_ok');
  el.hass = { states: s };
  const n0 = el.shadowRoot.writes;
  el.hass = { states: s };
  assert.equal(el.shadowRoot.writes, n0, 'same fingerprint');
  el.hass = { states: { ...s, 'sensor.unrelated_example': { entity_id: 'sensor.unrelated_example', state: '1', attributes: {} } } };
  assert.equal(el.shadowRoot.writes, n0, 'an unrelated entity changed: no re-render');
  const s2 = { ...s, [ids.status]: { ...s[ids.status], last_updated: '2030-01-15T21:15:00+00:00' } };
  el.hass = { states: s2 };
  assert.equal(el.shadowRoot.writes, n0 + 1);
});

test('an open details block stays open across a re-render', () => {
  const el = make();
  el._now = () => nowFor('synthetic_ok');
  el.hass = { states: statesFor('synthetic_ok') };
  el.shadowRoot.querySelector('details[data-k="drill"]').setAttribute('open', '');
  el._render();
  assert.equal(el.shadowRoot.querySelector('details[data-k="drill"]').hasAttribute('open'), true);
});

test('timer: one interval while connected, cleared on disconnect; the tick re-renders (report age, expiry)', () => {
  mock.timers.enable({ apis: ['setInterval'] });
  try {
    const el = make();
    let now = nowFor('synthetic_ok');
    el._now = () => now;
    el.hass = { states: statesFor('synthetic_ok') };
    el.connectedCallback();
    el.connectedCallback();
    const t = el._timer;
    assert.notEqual(t, null);
    assert.equal(el._timer, t, 'a second connect keeps the one interval');
    now += 60 * 60 * 1000; // an hour later: past valid_until
    mock.timers.tick(mod.TICK_MS);
    assert.equal(el.shadowRoot.querySelector('[data-callout="expired"]') !== null, true);
    assert.equal(el.shadowRoot.querySelectorAll('[data-fig]').length, 0);
    el.disconnectedCallback();
    assert.equal(el._timer, null);
  } finally {
    mock.timers.reset();
  }
});

test('setConfig errors surface to Home Assistant (thrown), and nothing renders before a configuration', () => {
  const el = new EccoIntelligenceCard();
  el.hass = { states: statesFor('synthetic_ok') };
  assert.equal(el.shadowRoot.writes, 0);
  assert.throws(() => el.setConfig({ entities: { status: 'sensor.ecco_intelligence_status' } }), /frozen V1 prototype/);
});
