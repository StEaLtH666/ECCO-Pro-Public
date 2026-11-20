// The card against the dashboard configuration that tools/geek_mode_dashboard_config.py GENERATES for the new admin-only dashboard (the first supervised
// Home Assistant update): the shell card's configuration, with the catalogue INLINE, is what Home Assistant would hand setConfig. The other suites prove the
// card with the catalogue read from its file and with hand-made child lists; this one proves the generated text itself:
//   - the shell card of the generated configuration is a valid configuration for the card, and its inline catalogue is the committed catalogue
//   - setConfig accepts it and builds Production and Geek Mode against the synthetic healthy fixture, with no configuration or catalogue alert
//   - the child cards are handed to Home Assistant's card helpers unchanged (the very same objects), three in Production
//   - Geek Mode shows the 17 sources and the 344 declared attribute rows, and the whole session touches nothing but hass.states, locale and themes
// The configuration is made by running the generator (ECCO_PYTHON, default python; it needs PyYAML), or read from the file named by ECCO_U1_CONFIG. Without
// either the tests are SKIPPED, loudly: a run that must not skip checks `skipped` in the node summary.
import test, { afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { installDom, installResizeObserver, MElement } from './minidom.mjs';

const { doc, win } = installDom(); // BEFORE the card module is evaluated
installResizeObserver();
const H = await import('./helpers.mjs');
const { loadCard, cardDir, realCatalogue, intelStates, makeHass, trapHass, installTraps, tick } = H;
const mod = await loadCard('generated-config');
const { EccoModeShell, TAG, validateConfig, validateCatalogue } = mod;

/** The generated configuration: { config } or { problem }. */
function generated() {
  const given = process.env.ECCO_U1_CONFIG;
  if (given) return { config: JSON.parse(readFileSync(path.resolve(given), 'utf8')) };
  const dir = mkdtempSync(path.join(tmpdir(), 'ecco-u1-config-'));
  try {
    const out = path.join(dir, 'dashboard.json');
    const tool = path.resolve(cardDir, '..', '..', 'tools', 'geek_mode_dashboard_config.py');
    const r = spawnSync(process.env.ECCO_PYTHON || 'python', ['-I', '-B', '-X', 'utf8', tool, '--out', out], { encoding: 'utf8', timeout: 60000 });
    if (r.status !== 0) return { problem: `the generator did not run (exit ${r.status}): ${String(r.stderr || r.stdout || r.error || '').slice(0, 200)}` };
    return { config: JSON.parse(readFileSync(out, 'utf8')) };
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

const GEN = generated();
const skip = GEN.problem ? `SKIPPED: ${GEN.problem}` : false;
const DASH = GEN.config || { views: [{ cards: [{}, {}] }] };
const SHELL = DASH.views[0].cards[0];

class StubCard extends MElement {
  constructor(type = 'stub-card') {
    super('stub-card');
    this.cardType = type;
    this.hassSeen = [];
  }

  setConfig(cfg) {
    this.config = cfg;
  }

  set hass(h) {
    this.hassSeen.push(h);
    this._hass = h;
  }

  get hass() {
    return this._hass;
  }
}

const live = new Set();
let made = [];
function mount(states, now, hass = null) {
  made = [];
  win.location.pathname = '/ecco-modes/intelligence';
  win.loadCardHelpers = async () => ({ createCardElement: (cfg) => { made.push(cfg); const s = new StubCard(cfg.type); s.setConfig(cfg); return s; } });
  const el = new EccoModeShell();
  live.add(el);
  el._now = () => now;
  el.setConfig(SHELL);
  el.hass = hass || makeHass(states);
  el.connectedCallback();
  return el;
}
afterEach(() => {
  for (const el of live) el.disconnectedCallback();
  live.clear();
  delete win.loadCardHelpers;
});

const root = (el) => el.shadowRoot;
const q = (el, sel) => root(el).querySelector(sel);
const qa = (el, sel) => root(el).querySelectorAll(sel);
const stripIds = (el) => qa(el, '[data-ecco-alert-strip] [data-alert-id]').map((n) => n.getAttribute('data-alert-id'));
const healthy = () => intelStates('healthy');
/** Open every row of the inspector (a row is looked up again after each click: opening one re-draws the list). */
function openAll(el) {
  for (const id of qa(el, '[data-inspector-row]').map((r) => r.getAttribute('data-source-id'))) {
    qa(el, '[data-inspector-row]').find((r) => r.getAttribute('data-source-id') === id).querySelector('[data-row-toggle]').click();
  }
}

test('generated config: the shell card of the generated dashboard is a valid configuration, with the committed catalogue inline', { skip }, () => {
  assert.equal(SHELL.type, `custom:${TAG}`);
  assert.equal(DASH.views.length, 1);
  assert.equal(DASH.views[0].cards.length, 2);
  assert.deepEqual(validateConfig(SHELL).errors, []);
  assert.deepEqual(SHELL.catalogue, realCatalogue());
  const v = validateCatalogue(SHELL.catalogue);
  assert.equal(v.ok, true, JSON.stringify(v.errors || []).slice(0, 300));
  assert.equal(SHELL.catalogue.sources.length, 17);
  assert.equal(SHELL.catalogue.sources.reduce((n, s) => n + (s.attributes || []).length, 0), 344);
  assert.equal(SHELL.catalogue.alerts.length, 19);
  assert.equal(SHELL.always.length, 2);
  assert.equal(SHELL.production.length, 1);
  assert.equal(JSON.stringify(SHELL).includes('!include'), false);
});

test('generated config: setConfig accepts it and Production builds against the healthy fixture, with no configuration or catalogue alert', { skip }, async () => {
  const f = healthy();
  const el = mount(f.states, f.now);
  await tick();
  await tick();
  assert.equal(el.mode, 'production');
  const ids = stripIds(el);
  assert.equal(ids.includes('shell:catalogue-invalid'), false, ids.join(','));
  assert.equal(ids.includes('shell:config-invalid'), false, ids.join(','));
  assert.equal(ids.includes('shell:child-refused'), false, ids.join(','));
  assert.ok(q(el, '[data-ecco-alert-strip]'));
  assert.equal(qa(el, '[data-child-error]').length, 0, 'no child card failed to be created');
  assert.equal(qa(el, 'stub-card').length, 3, 'the two always cards and the one production card');
  assert.equal(el.snapshot.rows.filter((r) => !r.discovered).length, 17);
});

test('generated config: the child cards reach Home Assistant\'s card helpers unchanged (the very same objects), and receive hass', { skip }, async () => {
  const f = healthy();
  const el = mount(f.states, f.now);
  await tick();
  await tick();
  assert.equal(made.length, 3);
  assert.ok(SHELL.always.every((c) => made.includes(c)), 'every always card is passed as the same object');
  assert.ok(SHELL.production.every((c) => made.includes(c)), 'the production card is passed as the same object');
  assert.deepEqual(made.map((c) => c.type).sort(), ['custom:ecco-intelligence-card', 'entities', 'tile']);
  assert.ok(qa(el, 'stub-card').every((k) => k.hassSeen.length >= 1));
});

test('generated config: Geek Mode shows the 17 sources and the 344 declared attribute rows, and the Production-only tile is hidden', { skip }, async () => {
  const f = healthy();
  const el = mount(f.states, f.now);
  await tick();
  await tick();
  assert.equal(q(el, '[data-ecco-body="production"]').hidden, false);
  assert.equal(q(el, '[data-ecco-body="geek"]').hidden, true);
  q(el, '[data-mode-option="geek"]').click();
  assert.equal(el.mode, 'geek');
  assert.equal(q(el, '[data-ecco-body="production"]').hidden, true, 'the Production body (the pause tile lives there) is hidden in Geek Mode');
  assert.equal(q(el, '[data-ecco-body="geek"]').hidden, false);
  const ids = qa(el, '[data-inspector-row]').map((r) => r.getAttribute('data-source-id'));
  assert.equal(ids.length, 17, 'the 17 sources on the first page');
  openAll(el);
  const declared = new Set();
  for (const r of qa(el, '[data-inspector-row]')) {
    for (const a of r.querySelectorAll('[data-attribute-path]')) {
      if (a.getAttribute('data-declared') === 'true') declared.add(`${r.getAttribute('data-source-id')}#${a.getAttribute('data-attribute-path')}`);
    }
  }
  const want = new Set(SHELL.catalogue.sources.flatMap((s) => (s.attributes || []).map((a) => `${s.id}#${a.name}`)));
  assert.equal(want.size, 344);
  assert.deepEqual([...declared].sort(), [...want].sort(), 'every declared attribute row is listed once its source is opened (344, each once)');
  assert.ok(q(el, '[data-ecco-alert-strip]'), 'the alert strip is still there in Geek Mode');
  q(el, '[data-mode-option="production"]').click();
  assert.equal(el.mode, 'production');
  assert.equal(q(el, '[data-ecco-body="production"]').hidden, false);
});

test('generated config: both modes and a state change touch nothing but hass.states, locale and themes (no service, no websocket, no storage, no network)', { skip }, async () => {
  const f = healthy();
  const { hass, calls } = trapHass(f.states);
  const traps = installTraps();
  try {
    const el = mount(f.states, f.now, hass);
    await tick();
    await tick();
    q(el, '[data-mode-option="geek"]').click();
    openAll(el);
    q(el, '[data-mode-option="production"]').click();
    el.hass = trapHass({ ...f.states }).hass;
    await tick();
    assert.deepEqual(calls, [], 'no hass function was called and no other hass property was read');
    assert.deepEqual(traps.hits, [], 'no storage, network, window.open or history access');
  } finally {
    traps.restore();
  }
});
