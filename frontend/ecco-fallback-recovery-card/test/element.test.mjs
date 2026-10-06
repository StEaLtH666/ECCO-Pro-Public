// Custom-element tests against a minimal fake DOM: registration, service-call hygiene, timers, patching.
// The browser-only parts (real shadow DOM, focus, clipboard permissions) are exercised through preview/index.html.
import test, { mock, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { scenarios, IDS, T0, hassFor, statesFor, withStates, callsOf, touchedOf } from './helpers.mjs';

// ---- minimal browser stand-ins, installed BEFORE the card module is evaluated ----
class FakeHTMLElement {}
const registry = new Map();
globalThis.HTMLElement = FakeHTMLElement;
globalThis.customElements = { get: (n) => registry.get(n), define: (n, c) => registry.set(n, c) };
globalThis.window = {};
globalThis.CustomEvent = class { constructor(type, init = {}) { this.type = type; this.detail = init.detail; this.bubbles = init.bubbles; this.composed = init.composed; } };
const store = new Map();
globalThis.localStorage = { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)) };

const mod = await import('../ecco-fallback-recovery-card.js?element');
const { EccoFallbackRecoveryCard, TAG, DETAIL_STORAGE_KEY } = mod;

// FB-B2 (CARD-14): every card a test creates is disconnected after the test, pass or fail. A failing assertion used to leave a live 1 Hz
// interval behind (the sections after mock.timers.reset() run on real timers), and `node --test` then never exited.
const liveCards = new Set();
{
  const setConfig = EccoFallbackRecoveryCard.prototype.setConfig;
  EccoFallbackRecoveryCard.prototype.setConfig = function track(config) {
    liveCards.add(this);
    return setConfig.call(this, config);
  };
}
afterEach(() => {
  for (const el of liveCards) {
    try { el.disconnectedCallback(); } catch (e) { /* already torn down */ }
  }
  liveCards.clear();
});

function topLevel(html) {
  const out = [];
  let depth = 0;
  let start = 0;
  const re = /<(\/?)div\b[^>]*>/g;
  let m;
  while ((m = re.exec(html)) !== null) {
    if (m[1]) {
      depth -= 1;
      if (depth === 0) { out.push(html.slice(start, re.lastIndex)); start = re.lastIndex; }
    } else depth += 1;
  }
  return out;
}

class FakeKid {
  constructor(html, parent) {
    this.html = html;
    this.parent = parent;
    this.innerHTMLWrites = [];
    this.attrs = {};
  }
  get innerHTML() { return this.html.replace(/^<[^>]*>/, '').replace(/<\/div>$/, ''); }
  set innerHTML(h) { this.innerHTMLWrites.push(h); this.html = this.html.replace(/^(<[^>]*>)[\s\S]*(<\/div>)$/, `$1${h}$2`); this.parent.ops.push(['live', h]); }
  getAttribute(k) { const m = new RegExp(`^<[^>]*\\s${k}="([^"]*)"`).exec(this.html); return m ? m[1] : null; }
  setAttribute(k, v) { this.attrs[k] = v; }
  removeAttribute(k) { delete this.attrs[k]; }
  replaceWith(nk) { this.parent.ops.push(['replace', nk.html]); this.html = nk.html; }
}
const fakeDoc = {
  createElement() {
    const tpl = { content: {} };
    Object.defineProperty(tpl, 'innerHTML', { set(h) { tpl.content.firstElementChild = new FakeKid(h, { ops: [] }); } });
    return tpl;
  },
};
class FakeCardEl {
  constructor(id) { this.id = id; this.className = ''; this.attrs = {}; this.props = {}; this.ops = []; this._html = ''; this.children = []; this.ownerDocument = fakeDoc; this.style = { setProperty: (k, v) => { this.props[k] = v; } }; }
  get innerHTML() { return this._html; }
  set innerHTML(h) { this._html = h; this.ops.push(['html']); this.children = topLevel(h).map((k) => new FakeKid(k, this)); }
  contains() { return false; }
  querySelector() { return null; }
  setAttribute(k, v) { this.attrs[k] = v; }
  removeAttribute(k) { delete this.attrs[k]; }
}
function fakeRoot() {
  const els = {};
  const root = {
    els,
    activeElement: null,
    timeWrites: [],
    getElementById: (id) => (els[id] ||= new FakeCardEl(id)),
    querySelectorAll(sel) {
      if (sel !== '[data-t]') return [];
      const html = Object.values(els).map((e) => e.children.map((k) => k.html).join('') || e._html).join('');
      return [...html.matchAll(/data-t="(\w+)"/g)].map((m) => ({
        getAttribute: () => m[1],
        _t: '',
        get textContent() { return this._t; },
        set textContent(v) { this._t = v; root.timeWrites.push([m[1], v]); },
      }));
    },
    querySelector: () => null,
    listeners: {},
    // FB-B2 (CARD-09): the card's click listener is kept, so a test can deliver a click the way a browser does (see `press`)
    addEventListener(type, fn) { root.listeners[type] = fn; },
  };
  return root;
}

function makeCard(scenario = 'idle_saved', { helper = null, config = {}, withRoot = false } = {}) {
  // a card with the string-level fake root starts from clean storage: a leftover "technical detail open" from an
  // earlier test would render card 7's body, which this stub does not model (dom.test.mjs covers that on a real tree)
  if (withRoot) store.clear();
  const el = new EccoFallbackRecoveryCard();
  if (withRoot) el._root = fakeRoot();
  el.setConfig({ type: `custom:${TAG}`, entities: { ...IDS }, ...(helper ? { technical_detail_entity: helper.id } : {}), ...config });
  const h = hassFor(scenarios[scenario], T0, helper);
  el.hass = h;
  return { el, h };
}

const ALLOWED = (h, cfg) => callsOf(h).every((c) => (c.domain === 'button' && c.service === 'press' && c.data.entity_id === cfg.review) || (c.domain === 'input_boolean' && c.service === 'toggle' && c.data.entity_id === cfg.helper));

// ---------------------------------------------------------------------------
test('import registers the element and the card-picker entry exactly once, and is idempotent', async () => {
  assert.equal(registry.get(TAG), EccoFallbackRecoveryCard);
  assert.equal(window.customCards.filter((c) => c.type === TAG).length, 1);
  assert.equal(window.customCards[0].preview, false);
  assert.match(window.customCards[0].name, /ECCO Fallback \/ Recovery Card/);
  await import('../ecco-fallback-recovery-card.js?element-second-instance');
  assert.equal(registry.size, 1, 'a second evaluation does not re-define the tag');
  assert.equal(window.customCards.filter((c) => c.type === TAG).length, 1, 'nor duplicate the picker entry');
});

test('setConfig validates; stub config is valid; grid options and size are provided', () => {
  const el = new EccoFallbackRecoveryCard();
  assert.throws(() => el.setConfig({}), /entities/);
  assert.throws(() => el.setConfig({ entities: { ...IDS, review_button: 'switch.x' } }), /button/);
  assert.doesNotThrow(() => el.setConfig(EccoFallbackRecoveryCard.getStubConfig()));
  assert.equal(EccoFallbackRecoveryCard.getStubConfig().type, 'custom:ecco-fallback-recovery-card');
  assert.deepEqual(el.getGridOptions(), { columns: 'full', rows: 'auto', min_columns: 12, min_rows: 6 });
  assert.ok(el.getCardSize() >= 10);
  // setting hass before the config is harmless
  const early = new EccoFallbackRecoveryCard();
  early.hass = hassFor(scenarios.idle_saved);
  assert.equal(early._vm, null);
  early.setConfig({ entities: { ...IDS } });
  assert.equal(early._vm.profile, 'saved', 'the held hass is applied when the config arrives');
});

test('Review: exactly one button.press on the configured button, then a debounce', () => {
  const { el, h } = makeCard('idle_saved');
  const r = el._act('review');
  assert.equal(r.sent, true);
  assert.deepEqual(callsOf(h), [{ domain: 'button', service: 'press', data: { entity_id: IDS.review_button } }]);
  assert.deepEqual(el._act('review'), { sent: false, why: 'Review requested' }, 'a second click inside the debounce is ignored');
  assert.equal(callsOf(h).length, 1);
  // the firmware answering (B3 changes) ends the debounce
  const reading = { ...scenarios.idle_saved, review: scenarios.reading.review, last_result: scenarios.reading.last_result };
  el.hass = hassFor(reading, T0 + 100);
  assert.equal(el._pendingUntil, 0);
  assert.deepEqual(el._act('review'), { sent: false, why: 'Review in progress' });
  assert.equal(callsOf(h).length, 1);
  el.disconnectedCallback();
});

test('Review is never sent while disabled: reading, write lock, unavailable, unknown status, no button', () => {
  for (const [name, why] of [
    ['reading', 'Review in progress'],
    ['refused_lock', 'Inverter bus busy - try again shortly'],
    ['unavailable', 'Entities unavailable'],
    ['partial_unavailable', 'Entities unavailable'],
    ['st_unrecognised', 'Review status not recognised'],
    ['button_unavailable', 'Review button unavailable'],
  ]) {
    const { el, h } = makeCard(name);
    assert.deepEqual(el._act('review'), { sent: false, why }, name);
    assert.equal(callsOf(h).length, 0, name);
  }
  // candidates, refusals and read errors are all re-reviewable
  for (const name of ['ready_diff', 'mismatch', 'refused', 'read_error', 'expired', 'not_saveable']) {
    const { el, h } = makeCard(name);
    assert.equal(el._act('review').sent, true, name);
    assert.equal(callsOf(h).length, 1, name);
    el.disconnectedCallback();
  }
});

test('Review failures surface a notice instead of failing silently', async () => {
  const { el, h } = makeCard('idle_saved');
  h.callService = () => Promise.reject(new Error('rejected'));
  el._act('review');
  await new Promise((r) => setTimeout(r, 5));
  assert.match(el._ui.notice, /Home Assistant did not accept the request/);
  assert.match(el._lastRender.cards.c3.inner, /Home Assistant did not accept the request\. Check the connection and try again\./);
  el.disconnectedCallback();
  const throwing = makeCard('idle_saved');
  throwing.h.callService = () => { throw new Error('sync boom'); };
  assert.equal(throwing.el._act('review').sent, false);
  assert.match(throwing.el._ui.notice, /did not accept/);
  throwing.el.disconnectedCallback();
  const noHass = makeCard('idle_saved');
  noHass.h.callService = undefined;
  assert.equal(noHass.el._act('review').sent, false);
  assert.match(noHass.el._ui.notice, /not connected/);
  noHass.el.disconnectedCallback();
});

test('technical detail: per-viewer localStorage by default, helper toggle when configured and reporting', () => {
  store.clear();
  const { el, h } = makeCard('idle_saved');
  assert.equal(el._detailOpen(), false);
  const r = el._act('toggle-detail');
  assert.deepEqual(r, { sent: false, helper: false });
  assert.equal(el._detailOpen(), true);
  assert.equal(store.get(DETAIL_STORAGE_KEY), '1');
  assert.equal(callsOf(h).length, 0, 'no service call for the per-viewer toggle');
  assert.match(el._lastRender.cards.c7.inner, /aria-expanded="true"/);
  // a new card instance in the same browser remembers it
  const again = makeCard('idle_saved');
  assert.equal(again.el._detailOpen(), true);
  el._act('toggle-detail');
  assert.equal(store.get(DETAIL_STORAGE_KEY), '0');

  const helper = { id: 'input_boolean.example_detail', state: 'off' };
  const hc = makeCard('idle_saved', { helper });
  assert.equal(hc.el._detailOpen(), false);
  const r2 = hc.el._act('toggle-detail');
  assert.deepEqual(r2, { sent: true, helper: true });
  assert.deepEqual(callsOf(hc.h), [{ domain: 'input_boolean', service: 'toggle', data: { entity_id: 'input_boolean.example_detail' } }]);
  assert.equal(hc.el._detailOpen(), true, 'optimistic until Home Assistant echoes the helper state');
  hc.el.hass = hassFor(scenarios.idle_saved, T0 + 500, { id: helper.id, state: 'on' });
  assert.equal(hc.el._detailOpen(), true);
  // the helper reporting "unavailable" falls back to the per-viewer value, with no service call
  const hu = makeCard('idle_saved', { helper: { id: helper.id, state: 'unavailable' } });
  assert.equal(hu.el._act('toggle-detail').helper, false);
  assert.equal(callsOf(hu.h).length, 0);
});

test('a throwing localStorage never breaks the card', () => {
  const saved = globalThis.localStorage;
  globalThis.localStorage = { getItem() { throw new Error('SecurityError'); }, setItem() { throw new Error('QuotaExceededError'); } };
  try {
    const { el } = makeCard('idle_saved');
    assert.equal(el._detailOpen(), false);
    assert.doesNotThrow(() => el._act('toggle-detail'));
    assert.equal(el._detailOpen(), true, 'the in-memory value still works');
  } finally {
    globalThis.localStorage = saved;
  }
});

test('every action the card can take only ever calls the two allowed services', () => {
  const helper = { id: 'input_boolean.example_detail', state: 'on' };
  for (const name of ['idle_saved', 'ready_diff', 'not_saveable', 'unavailable', 'reading', 'refused']) {
    const { el, h } = makeCard(name, { helper });
    const cfg = { review: IDS.review_button, helper: helper.id };
    for (const act of ['review', 'toggle-detail', 'view', 'copy', 'more-info', 'goto-summary', 'save', 'invalidate', 'restore', 'arm', 'noop', undefined]) {
      try { el._act(act, { view: 'saved', copyKey: 'review', ent: 'profile_state' }); } catch (e) { /* a refusal is fine */ }
    }
    assert.ok(ALLOWED(h, cfg), `${name}: ${JSON.stringify(callsOf(h))}`);
    assert.deepEqual(touchedOf(h), [], `${name}: no hass member other than states / locale / config / language / callService was touched`);
    el.disconnectedCallback();
  }
  // the guard itself: a hand-built call outside the allowlist throws before reaching hass
  const { el, h } = makeCard('idle_saved');
  assert.throws(() => el._call({ domain: 'switch', service: 'turn_on', data: { entity_id: 'switch.x' } }), /not allowed/);
  assert.throws(() => el._call({ domain: 'button', service: 'press', data: { entity_id: 'button.other' } }), /not allowed/);
  assert.equal(callsOf(h).length, 0);
});

test('the mock hass is strict: any member the card is not allowed to use throws and is recorded', () => {
  const h = hassFor(scenarios.idle_saved);
  for (const k of ['callWS', 'callApi', 'sendMessage', 'connection', 'auth', 'user', 'services']) {
    assert.throws(() => h[k], /never use/, k);
  }
  assert.throws(() => { h.callApi = () => {}; }, /never use/);
  assert.throws(() => 'callWS' in h, /never use/);
  assert.deepEqual(touchedOf(h), ['callWS', 'callApi', 'sendMessage', 'connection', 'auth', 'user', 'services', 'callApi', 'callWS']);
  for (const k of ['states', 'locale', 'config', 'language', 'callService']) assert.doesNotThrow(() => h[k], k);
  // a card that reached for callWS would fail loudly here instead of silently finding nothing
  const { el, h: bad } = makeCard('idle_saved');
  el._hass = withStates(bad, bad.states);
  assert.doesNotThrow(() => el._act('review'));
  assert.deepEqual(touchedOf(el._hass), []);
  el.disconnectedCallback();
});

test('summary selector and more-info actions', () => {
  const { el } = makeCard('ready_diff');
  assert.equal(el._ui.view, 'auto');
  el._act('view', { view: 'saved' });
  assert.equal(el._ui.view, 'saved');
  assert.match(el._lastRender.cards.c6.inner, /aria-pressed="true" aria-disabled="false">Saved profile g7</);
  el._act('view', { view: 'cand' });
  assert.equal(el._ui.view, 'cand');
  el._act('view', { view: 'bogus' });
  assert.equal(el._ui.view, 'cand');
  const idle = makeCard('idle_saved').el;
  idle._act('view', { view: 'cand' });
  assert.equal(idle._ui.view, 'auto', 'a disabled segment ignores the click');
  const events = [];
  el.dispatchEvent = (e) => events.push(e);
  assert.equal(el._act('more-info', { ent: 'profile_state' }), true);
  assert.equal(events[0].type, 'hass-more-info');
  assert.deepEqual(events[0].detail, { entityId: IDS.profile_state });
  assert.equal(events[0].bubbles && events[0].composed, true);
  assert.equal(el._act('more-info', { ent: 'not_a_key' }), false);
});

test('copy takes the live raw string or the ungrouped candidate ID', async () => {
  const written = [];
  Object.defineProperty(globalThis, 'navigator', { value: { clipboard: { writeText: async (t) => written.push(t) } }, configurable: true });
  const { el } = makeCard('ready_diff');
  assert.equal(await el._act('copy', { copyKey: 'id' }), 'copied');
  assert.equal(await el._act('copy', { copyKey: 'review' }), 'copied');
  assert.deepEqual(written, ['9C21B04E7D185F3A', scenarios.ready_diff.review]);
  assert.equal(await el._act('copy', { copyKey: 'nope' }), 'nothing');
  el.disconnectedCallback();
});

// ---------------------------------------------------------------------------
// ticking
// ---------------------------------------------------------------------------
test('the 1 Hz tick runs only while a candidate is on screen and is derived from exp and last_changed', () => {
  mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: T0 });
  try {
    const { el } = makeCard('idle_saved', { withRoot: true });
    el.connectedCallback();
    assert.equal(el._timer, null, 'no candidate, no timer');
    // candidate appears: exp=112 published at T0
    el.hass = hassFor(scenarios.ready_diff, T0);
    assert.notEqual(el._timer, null);
    assert.equal(el._anchor.exp, 112);
    assert.equal(el._anchor.at, T0);
    const rem = () => el._root.timeWrites.filter((w) => w[0] === 'rem').slice(-1)[0][1];
    mock.timers.tick(1000);
    assert.equal(rem(), '1:51');
    mock.timers.tick(4000);
    assert.equal(rem(), '1:47');
    // the firmware re-publishes exp every 10 s: the countdown snaps to it
    mock.timers.tick(5000);
    el.hass = hassFor({ ...scenarios.ready_diff, review: scenarios.ready_diff.review.replace('exp=112', 'exp=102') }, T0 + 10_000);
    assert.equal(el._anchor.exp, 102);
    assert.equal(el._anchor.at, T0 + 10_000);
    mock.timers.tick(1000);
    assert.equal(rem(), '1:41');
    // candidate gone (expired): the timer stops
    el.hass = hassFor(scenarios.expired, T0 + 15_000);
    assert.equal(el._timer, null);
    assert.equal(el._anchor, null);
    el.disconnectedCallback();
  } finally {
    mock.timers.reset();
  }
});

test('the countdown reaches "expiring…" and waits for the firmware; the tick stops long after the last publish', () => {
  mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: T0 });
  try {
    const { el } = makeCard('idle_saved', { withRoot: true });
    el.connectedCallback();
    el.hass = hassFor(scenarios.ready_expiring, T0 + 1);
    assert.notEqual(el._timer, null);
    mock.timers.tick(13_000);
    const last = el._root.timeWrites.filter((w) => w[0] === 'rem').slice(-1)[0][1];
    assert.equal(last, 'expiring…');
    assert.doesNotMatch(el._lastRender.cards.c4.inner, /Candidate expired\./, 'the card never declares expiry itself');
    assert.match(el._lastRender.cards.c4.inner, /Expiring - waiting for the firmware/);
    assert.notEqual(el._timer, null, 'still waiting for the firmware');
    mock.timers.tick(700_000);
    assert.equal(el._timer, null, 'a candidate that never clears does not keep a timer running forever');
    el.disconnectedCallback();
  } finally {
    mock.timers.reset();
  }
});

test('the 15 s transition is announced once; the countdown itself is silent', () => {
  mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: T0 });
  try {
    const { el } = makeCard('idle_saved', { withRoot: true });
    el.connectedCallback();
    el.hass = hassFor(scenarios.ready_expiring, T0);
    assert.equal(el._lastAnnouncement, 'Candidate expires in 12 seconds', 'first render already inside the last 15 s');
    mock.timers.tick(1000);
    mock.timers.tick(1000);
    assert.equal(el._lastAnnouncement, 'Candidate expires in 12 seconds', 'no re-announcement while counting down');
    el.disconnectedCallback();
    const long = makeCard('idle_saved', { withRoot: true });
    long.el.connectedCallback();
    long.el.hass = hassFor(scenarios.ready_diff, Date.now());
    assert.equal(long.el._lastAnnouncement, undefined);
    mock.timers.tick(96_000);
    assert.equal(long.el._lastAnnouncement, undefined, 'silent while more than 15 s are left');
    mock.timers.tick(1000);
    assert.equal(long.el._lastAnnouncement, 'Candidate expires in 15 seconds', 'announced once at the 15 s transition');
    mock.timers.tick(5000);
    assert.equal(long.el._lastAnnouncement, 'Candidate expires in 15 seconds');
    long.el.disconnectedCallback();
  } finally {
    mock.timers.reset();
  }
});

test('disconnecting stops every timer', () => {
  mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: T0 });
  try {
    const { el } = makeCard('idle_saved', { withRoot: true });
    el.connectedCallback();
    el.hass = hassFor(scenarios.ready_diff, T0);
    el._act('review');
    assert.notEqual(el._timer, null);
    assert.notEqual(el._pendingTimer, null);
    el.disconnectedCallback();
    assert.equal(el._timer, null);
    assert.equal(el._pendingTimer, null);
  } finally {
    mock.timers.reset();
  }
});

// ---------------------------------------------------------------------------
// patching: no DOM churn on a tick, live regions updated in place
// ---------------------------------------------------------------------------
test('a tick writes only the time texts: no card markup is replaced while the bucket is unchanged', () => {
  mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: T0 });
  try {
    const { el } = makeCard('idle_saved', { withRoot: true });
    el.connectedCallback();
    el.hass = hassFor(scenarios.ready_diff, T0);
    const els = el._root.els;
    const writes = () => Object.values(els).reduce((n, e) => n + e.ops.length, 0);
    const before = writes();
    assert.ok(before > 0);
    mock.timers.tick(1000);
    mock.timers.tick(1000);
    mock.timers.tick(1000);
    assert.equal(writes(), before, 'three ticks, zero markup writes');
    // across the "soon" boundary (rem 45 at +67 s) only the count block of the review card is replaced
    const c3Before = els.c3.ops.length;
    mock.timers.tick(64_000);
    const ops = els.c3.ops.slice(c3Before);
    assert.deepEqual(ops.map((o) => o[0]), ['replace'], 'only the countdown block changed (live regions untouched)');
    el.disconnectedCallback();
  } finally {
    mock.timers.reset();
  }
});

test('a state change updates the review live regions in place instead of replacing them', () => {
  const { el } = makeCard('idle_saved', { withRoot: true });
  const c3 = el._root.els.c3;
  assert.deepEqual(c3.ops.map((o) => o[0]), ['html'], 'first paint');
  const headBefore = c3.children[1];
  el.hass = hassFor(scenarios.reading, T0 + 50);
  const kinds = c3.ops.slice(1).map((o) => o[0]);
  assert.ok(kinds.includes('live'), JSON.stringify(kinds));
  assert.equal(c3.children[1], headBefore, 'the same element object keeps its live region');
  assert.match(headBefore.html, /READING INVERTER/);
  assert.equal(c3.attrs['data-act'], undefined);
  assert.equal(el._root.els.c1.attrs['data-act'], 'more-info');
  assert.equal(el._root.els.c1.attrs['data-ent'], 'profile_state');
  assert.equal(c3.props['--state'], 'var(--busy)');
});

test('hass pushes that do not touch the configured entities cause no re-render', () => {
  const { el, h } = makeCard('ready_diff', { withRoot: true });
  let renders = 0;
  const orig = el._renderCards.bind(el);
  el._renderCards = () => { renders += 1; return orig(); };
  const noisy = withStates(h, { ...h.states, 'sensor.something_else': { state: '1', last_changed: new Date(T0).toISOString() } });
  el.hass = noisy;
  el.hass = withStates(noisy, { ...noisy.states, 'sensor.something_else': { state: '2', last_changed: new Date(T0 + 1).toISOString() } });
  assert.equal(renders, 0);
  el.hass = hassFor(scenarios.reading, T0 + 100);
  assert.equal(renders, 1);
  el.disconnectedCallback();
});

test('the header follows show_header', () => {
  const on = makeCard('idle_saved', { withRoot: true });
  assert.match(on.el._lastRender.header, /Fallback \/ Recovery/);
  const off = makeCard('idle_saved', { withRoot: true, config: { show_header: false } });
  assert.equal(off.el._lastRender.header, '');
  const titled = makeCard('idle_saved', { withRoot: true, config: { title: 'My title' } });
  assert.match(titled.el._lastRender.header, /My title/);
});

// ---------------------------------------------------------------------------
// FB-B2: guarded Save / Invalidate. Only a trusted user click sends anything; one request per click; no retry.
// ---------------------------------------------------------------------------
const ARM = IDS.arm;
const EXEC = 'ecco_clock_dongle_fallback_profile_execute';
const RID = '5F3A9C21B04E7D18'; // the B4 review id of ready_match / arm_on_ready
const PID = '2BAEBFE97F4E04BC'; // the B2 binding of idle_saved
const click = { trusted: true };
const turnOn = { domain: 'switch', service: 'turn_on', data: { entity_id: ARM } };
const turnOff = { domain: 'switch', service: 'turn_off', data: { entity_id: ARM } };
const execCall = (action, id, phrase) => ({ domain: 'esphome', service: EXEC, data: { action, target_id: id, confirmation: phrase } });

/** A card on a string-level root, a mocked clock, and the first publish of scenario `name` (now; the arm last changed at `armMs`). */
function armedCard(name, { armMs = null, intent = null } = {}) {
  const base = Date.now();
  const el = new EccoFallbackRecoveryCard();
  el._root = fakeRoot();
  store.clear();
  el.setConfig({ type: `custom:${TAG}`, entities: { ...IDS } });
  el.connectedCallback();
  // Home Assistant only moves an entity's last_changed when its state changes: remember each state with its change time
  const memo = {};
  const stampsFor = (E, ms, stamps) => {
    const out = {};
    for (const k of Object.keys(E)) {
      if (!memo[k] || memo[k].state !== E[k]) memo[k] = { state: E[k], ms: stamps[k] !== undefined ? stamps[k] : ms };
      out[k] = memo[k].ms;
    }
    return out;
  };
  let h = hassFor(scenarios[name], base, null, stampsFor(scenarios[name], base, { arm: armMs === null ? base : armMs }));
  el.hass = h;
  // FB-B2 (CARD-08): an arm that is on is "for a save" only when THIS card switched it on; a test that wants the confirmation says so
  if (intent) {
    el._ui.intent = intent;
    el._renderCards();
  }
  /** Publish again with the SAME call log: scenario `s` plus `patch`; `ms` stamps what changed, `stamps` single keys. */
  const publish = (s, patch = {}, ms = Date.now(), stamps = {}) => {
    const E = { ...scenarios[s], ...patch };
    h = withStates(h, statesFor(E, ms, null, stampsFor(E, ms, stamps)));
    el.hass = h;
    return h;
  };
  return { el, get h() { return h; }, publish, calls: () => callsOf(h) };
}

const fakeTarget = (attrs) => {
  const target = { tagName: 'BUTTON', closest: () => target, getAttribute: (k) => (k in attrs ? attrs[k] : null) };
  return target;
};

/**
 * FB-B2 (CARD-09): a click on a control, delivered the way a browser does it - through the click listener the card registered on its root.
 * The listener alone decides the trust: only `ds.trusted === true` makes the event a trusted one (isTrusted); anything else is a script-made
 * or flagless event. `ds.id` / `ds.variant` are the data-id / data-variant of the clicked button. Returns what the action returned.
 */
const press = (el, act, ds = {}) => {
  const attrs = {};
  if (act !== undefined) attrs['data-act'] = act;
  if (typeof ds.id === 'string') attrs['data-id'] = ds.id;
  if (typeof ds.variant === 'string') attrs['data-variant'] = ds.variant;
  return el._root.listeners.click({ target: fakeTarget(attrs), isTrusted: ds.trusted === true });
};

test('FB-B2 trusted clicks only: a click that is not isTrusted === true sends nothing, whatever the state', () => {
  mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: T0 });
  try {
    for (const [name, acts] of [
      ['ready_match', ['arm']],
      ['arm_on_ready', ['arm-cancel', 'save']],
      ['arm_on_no_candidate', ['arm-invalidate', 'arm-cancel', 'invalidate']],
    ]) {
      const c = armedCard(name);
      c.el._ui.intent = name === 'arm_on_no_candidate' ? 'invalidate' : 'save';
      c.el._renderCards();
      const refusal = { sent: false, why: 'Only a click on the button can start this.' };
      for (const act of acts) {
        const id = act === 'invalidate' ? PID : RID;
        // through the click listener: only isTrusted === true carries the pass
        for (const ds of [{}, { trusted: false }, { trusted: undefined }, { trusted: 'true' }, { trusted: 1 }, { trusted: null }]) {
          assert.deepEqual(press(c.el, act, { id, variant: 'save', ...ds }), refusal, `${name} ${act} ${JSON.stringify(ds)}`);
        }
        // FB-B2 (CARD-09), before: _act(act, { trusted: true, ... }) was a caller-supplied flag and worked. The trust decision is now made in the
        // listener closure, so no argument of the public methods can carry it: not the old flag, not a look-alike pass object
        for (const ds of [{ trusted: true }, { pass: true }, { pass: { trustedClick: true } }, { pass: Object.freeze({ trustedClick: true }) }, { trusted: true, pass: { trustedClick: true } }]) {
          assert.deepEqual(c.el._act(act, { id, variant: 'save', ...ds }), refusal, `${name} ${act} _act ${JSON.stringify(ds)}`);
        }
        // a script that calls the click handler itself (with an event object that claims to be trusted) holds no pass either
        const attrs = { 'data-act': act, 'data-id': id, 'data-variant': 'save' };
        for (const ev of [{ isTrusted: true }, { isTrusted: false }, {}, { isTrusted: 'true' }, { isTrusted: undefined }]) {
          assert.deepEqual(c.el._onClick({ target: fakeTarget(attrs), ...ev }), refusal, `${name} ${act} _onClick ${JSON.stringify(ev)}`);
          assert.deepEqual(c.el._onClick({ target: fakeTarget(attrs), ...ev }, { trustedClick: true }), refusal, `${name} ${act} _onClick with a forged pass`);
        }
        // the listener itself, with an untrusted event, also sends nothing
        for (const ev of [{ isTrusted: false }, {}, { isTrusted: 'true' }, { isTrusted: undefined }]) {
          c.el._root.listeners.click({ target: fakeTarget(attrs), ...ev });
        }
        assert.equal(c.calls().length, 0, `${name} ${act}: nothing was sent`);
      }
      c.el.disconnectedCallback();
    }
    // the positive control: the same walk through the listener with a trusted event DOES send (the guard is the pass, not a blanket refusal)
    const ok = armedCard('ready_match');
    assert.deepEqual(press(ok.el, 'arm', { trusted: true }), { sent: true });
    assert.equal(ok.calls().length, 1);
    ok.el.disconnectedCallback();
    // Review and the technical-detail toggle are not write controls of the guarded flow: they keep working on a normal click, a script-made one
    // included. FB-B2 (CARD-09): this is the honest limit of the trusted-click guard, and the README says so
    const c = armedCard('idle_saved');
    c.el._onClick({ target: fakeTarget({ 'data-act': 'review' }), isTrusted: false });
    assert.equal(c.calls().length, 1, 'Review is unchanged by FB-B2 (its own debounce and gates)');
    c.el.disconnectedCallback();
  } finally {
    mock.timers.reset();
  }
});

test('FB-B2 Arm Save: one switch.turn_on on the arm, never optimistic; the confirmation appears only when Home Assistant reports the arm on', () => {
  mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: T0 });
  try {
    const c = armedCard('ready_match');
    assert.doesNotMatch(c.el._lastRender.cards.c4.inner, /class="confirm"/);
    assert.deepEqual(press(c.el, 'arm', click), { sent: true });
    assert.deepEqual(c.calls(), [turnOn]);
    assert.equal(c.el._ui.intent, 'save');
    assert.doesNotMatch(c.el._lastRender.cards.c4.inner, /class="confirm"|data-act="save"/, 'not optimistic: the switch has not reported on yet');
    assert.match(c.el._lastRender.cards.c4.inner, /Arming…<\/button>/);
    // a second click while the request is pending is ignored (one call per click, no double submit)
    assert.deepEqual(press(c.el, 'arm', click), { sent: false, why: 'Arm requested' });
    assert.equal(c.calls().length, 1);
    // Home Assistant reports the switch on: now the confirmation panel is shown, with the arm countdown anchored there
    mock.timers.tick(300);
    c.publish('ready_match', { arm: 'on' }, Date.now(), { arm: Date.now() });
    assert.match(c.el._lastRender.cards.c4.inner, /<div class="confirm" role="group" aria-labelledby="confirm-save-title"/);
    assert.equal(c.el._armAnchor.at, T0 + 300);
    assert.equal(c.el._armAnchor.exp, 120);
    assert.equal(c.el._armPendingUntil, 0, 'the echo ends the pending state');
    assert.equal(c.calls().length, 1, 'nothing else was sent');
    assert.notEqual(c.el._timer, null, 'the 1 Hz tick runs for the arm countdown');
    // the confirmation never turns the arm on by itself again, however long it is open
    mock.timers.tick(60_000);
    assert.equal(c.calls().length, 1);
    c.el.disconnectedCallback();
  } finally {
    mock.timers.reset();
  }
});

test('FB-B2 Arm Save is refused, with no call, whenever a prerequisite fails or there is nothing to arm for', () => {
  mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: T0 });
  try {
    for (const [name, patch, why] of [
      ['ready_match', { supervision_stable: 'off', supervision_state: 'SUSPECT' }, 'Home Assistant heartbeat is not stable; wait until the dashboard shows it healthy, then review and save again'],
      ['ready_match', { ntp_synced: 'off' }, 'clock not NTP-synchronised this boot; the capture time would be untrusted'],
      ['ready_match', { dump_arm: 'on' }, 'a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first (on now: Dump to Grid)'],
      ['ready_match', { write_lock: 'on' }, 'another inverter transaction is in progress; try again shortly'],
      ['ready_match', { arm: 'unavailable' }, 'The arm entity is unavailable'],
      ['ready_match', { arm: 'on' }, 'The arm is already on'],
      ['not_saveable', {}, 'This candidate is not saveable: see the reasons above'],
      ['not_saveable_unreadable', {}, 'This candidate is not saveable: see the reasons above'],
      ['idle_saved', {}, 'no saveable candidate - press Review Current Configuration first'],
      ['reading', {}, 'another Fallback Profile operation is in progress'],
      ['saving', {}, 'another Fallback Profile operation is in progress'],
      ['unavailable', {}, 'The arm entity is unavailable'],
    ]) {
      const c = armedCard(name);
      c.publish(name, patch);
      const r = press(c.el, 'arm', click);
      assert.equal(r.sent, false, `${name} ${JSON.stringify(patch)}`);
      assert.equal(r.why, why, `${name} ${JSON.stringify(patch)}`);
      assert.equal(c.calls().length, 0);
      c.el.disconnectedCallback();
    }
    // no arm entity configured at all
    const el = new EccoFallbackRecoveryCard();
    el._root = fakeRoot();
    const noArm = Object.fromEntries(Object.entries(IDS).filter(([k]) => !['arm', 'free_power_arm', 'dump_arm', 'manual_arm'].includes(k)));
    el.setConfig({ type: `custom:${TAG}`, entities: noArm });
    const h = hassFor(scenarios.ready_match, T0);
    el.hass = h;
    for (const act of ['arm', 'arm-invalidate', 'arm-cancel', 'save', 'invalidate']) {
      const r = press(el, act, { ...click, id: RID });
      assert.equal(r.sent, false, act);
    }
    assert.equal(callsOf(h).length, 0);
    assert.match(el._lastRender.cards.c4.inner, /Saving is not set up on this dashboard/);
    // a candidate that has run out: the arm is refused (the firmware has not confirmed the expiry yet)
    const zero = armedCard('ready_expiring');
    mock.timers.tick(13_000);
    assert.equal(press(zero.el, 'arm', click).why, 'The candidate is expiring: review again');
    assert.equal(zero.calls().length, 0);
    zero.el.disconnectedCallback();
    el.disconnectedCallback();
  } finally {
    mock.timers.reset();
  }
});

test('FB-B2 Save: exactly one execute call with the on-screen ID and the exact phrase; the arm is not touched; no second call while pending', () => {
  mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: T0 });
  try {
    const c = armedCard('arm_on_ready', { intent: 'save' });
    mock.timers.tick(2000);
    assert.deepEqual(press(c.el, 'save', { ...click, id: RID, variant: 'save' }), { sent: true });
    assert.deepEqual(c.calls(), [execCall('SAVE', RID, `SAVE ${RID}`)], 'one call, no arm call, nothing else');
    assert.equal(c.el._ui.flow.state, 'sent');
    assert.equal(c.el._ui.flow.id, RID);
    assert.equal(c.el._ui.intent, 'sent', 'FB-B2 (CARD-04): the attempt used the arm up');
    assert.match(c.el._lastRender.cards.c4.inner, /class="headline">SAVE REQUESTED</);
    assert.doesNotMatch(c.el._lastRender.cards.c4.inner, /data-act="save"/);
    // a second click (the button is gone, but the handler does not trust the screen) is refused
    assert.deepEqual(press(c.el, 'save', { ...click, id: RID, variant: 'save' }), { sent: false, why: 'another Fallback Profile operation is in progress' });
    assert.deepEqual(press(c.el, 'arm-cancel', click).sent, true, 'turning the arm off is the safe direction and is still allowed');
    assert.equal(c.calls().length, 2);
    assert.deepEqual(c.calls()[1], turnOff);
    // Review is held while the request is unanswered
    assert.deepEqual(c.el._act('review'), { sent: false, why: 'Save in progress' });
    // the periodic B3 re-publish (exp ticks down) is NOT an answer: still pending, still no second call
    mock.timers.tick(10_000);
    c.publish('arm_on_ready', { review: scenarios.arm_on_ready.review.replace('exp=87', 'exp=76') });
    assert.equal(c.el._ui.flow.state, 'sent');
    assert.deepEqual(press(c.el, 'save', { ...click, id: RID, variant: 'save' }).sent, false);
    assert.equal(c.calls().length, 2);
    c.el.disconnectedCallback();
  } finally {
    mock.timers.reset();
  }
});

test('FB-B2 Save: SAVING, then the result. One call in total; the request state follows the dongle and nothing retries', () => {
  mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: T0 });
  try {
    const c = armedCard('arm_on_ready', { intent: 'save' });
    mock.timers.tick(1000);
    press(c.el, 'save', { ...click, id: RID, variant: 'save' });
    assert.equal(c.calls().length, 1);
    // the dongle accepts: arm off, candidate consumed, B3 SAVING, B9 progress
    mock.timers.tick(500);
    c.publish('saving', { profile_state: 'VALID' });
    assert.equal(c.el._ui.flow.state, 'running');
    assert.match(c.el._lastRender.cards.c4.inner, /class="headline">SAVE IN PROGRESS</);
    assert.match(c.el._lastRender.cards.c4.inner, /5F3A 9C21 B04E 7D18/, 'the consumed candidate stays named on screen');
    assert.match(c.el._lastRender.cards.c3.inner, /class="headline">SAVING</);
    assert.equal(c.el._ui.intent, null, 'the intent ended with the arm');
    // however long it runs, no automatic call
    mock.timers.tick(25_000);
    assert.equal(c.calls().length, 1);
    assert.equal(c.el._ui.flow.state, 'running', 'a running save is never timed out into a retry');
    // the result: saved
    c.publish('saved_ok');
    assert.equal(c.el._ui.flow, null);
    assert.match(c.el._lastRender.cards.c4.inner, /class="headline">SAVED</);
    assert.match(c.el._lastRender.cards.c4.inner, /Saved and verified this boot: generation 8/);
    mock.timers.tick(300_000);
    assert.equal(c.calls().length, 1, 'exactly one call for the whole save');
    // a Review afterwards is allowed again
    assert.equal(c.el._act('review').sent, true);
    c.el.disconnectedCallback();
  } finally {
    mock.timers.reset();
  }
});

test('FB-B2 Save: every refusal and failure outcome ends the request and is shown; the request is never repeated', () => {
  mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: T0 });
  try {
    for (const [result, word, mustMatch] of [
      ['save_refused_arm', 'SAVE REFUSED', /ECCO Fallback Profile Arm is not on/],
      ['save_refused_hb', 'SAVE REFUSED', /heartbeat is not stable/],
      ['save_changed', 'SAVE REFUSED', /live configuration changed since Review/],
      ['save_not_committed', 'SAVE NOT COMMITTED', /storage refused the write \(E102\); nothing changed/],
      ['save_stale_witness', 'SAVE NOT COMMITTED', /witness advanced/],
      ['save_unknown', 'SAVE OUTCOME UNKNOWN', /reboot the dongle \(when no temporary operation is active\)/],
    ]) {
      const c = armedCard('arm_on_ready', { intent: 'save' });
      press(c.el, 'save', { ...click, id: RID, variant: 'save' });
      mock.timers.tick(700);
      c.publish(result); // arm off, candidate consumed, B9 carries the outcome
      assert.equal(c.el._ui.flow, null, result);
      assert.equal(new RegExp(`class="headline">${word}<`).test(c.el._lastRender.cards.c4.inner), true, result);
      assert.match(c.el._lastRender.cards.c4.inner, mustMatch, result);
      assert.doesNotMatch(c.el._lastRender.cards.c4.inner, /data-act="save"/, `${result}: nothing to repeat`);
      mock.timers.tick(200_000);
      assert.equal(c.calls().length, 1, `${result}: one call, no retry`);
      c.el.disconnectedCallback();
    }
  } finally {
    mock.timers.reset();
  }
});

test('FB-B2 Save: no answer is a message after 30 s, never a retry; a rejected call is shown and never repeated', async () => {
  mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: T0 });
  try {
    const c = armedCard('arm_on_ready', { intent: 'save' });
    press(c.el, 'save', { ...click, id: RID, variant: 'save' });
    mock.timers.tick(29_000);
    assert.equal(c.el._ui.flow.state, 'sent');
    mock.timers.tick(1100);
    assert.equal(c.el._ui.flow.state, 'timeout');
    assert.match(c.el._lastRender.cards.c4.inner, /No result yet\. Check Last action before trying again; do not press Save twice\./);
    mock.timers.tick(600_000);
    assert.equal(c.calls().length, 1, 'ten minutes later: still the one call');
    assert.equal(c.el._ui.flow.state, 'timeout', 'the message stays until the dongle answers');
    // the dongle answers late: the message goes and the outcome shows
    c.publish('saved_ok');
    assert.equal(c.el._ui.flow, null);
    c.el.disconnectedCallback();
  } finally {
    mock.timers.reset();
  }
  // FB-B2 (CARD-14): from here on the timers are REAL. Each card is disconnected in a finally block (and by the afterEach net), so a failing
  // assertion can no longer leave a live 1 Hz interval behind: `node --test` printed the failure and then never exited.
  // Home Assistant rejects the call (ambiguous delivery): shown, never repeated
  let attempts = 0;
  const c = armedCard('arm_on_ready', { intent: 'save' });
  try {
    c.h.callService = () => { attempts += 1; return Promise.reject(new Error('rejected')); };
    press(c.el, 'save', { ...click, id: RID, variant: 'save' });
    await new Promise((r) => setTimeout(r, 5));
    assert.equal(attempts, 1);
    assert.equal(c.el._ui.flow.state, 'unsure');
    assert.match(c.el._ui.notice, /Home Assistant did not accept the request/);
    assert.match(c.el._lastRender.cards.c4.inner, /Home Assistant did not accept the request, so it may not have reached the dongle\. Check Last action before trying again\./);
    assert.equal(attempts, 1, 'no automatic second attempt');
  } finally {
    c.el.disconnectedCallback();
  }
  // a synchronous throw: nothing is pending
  const t = armedCard('arm_on_ready', { intent: 'save' });
  try {
    t.h.callService = () => { throw new Error('sync boom'); };
    assert.equal(press(t.el, 'save', { ...click, id: RID, variant: 'save' }).sent, false);
    assert.equal(t.el._ui.flow, null);
    assert.match(t.el._ui.notice, /did not accept/);
  } finally {
    t.el.disconnectedCallback();
  }
  const none = armedCard('arm_on_ready', { intent: 'save' });
  try {
    none.h.callService = undefined;
    assert.equal(press(none.el, 'save', { ...click, id: RID, variant: 'save' }).sent, false);
    assert.equal(none.el._ui.flow, null);
    assert.match(none.el._ui.notice, /not connected/);
  } finally {
    none.el.disconnectedCallback();
  }
});

test('FB-B2 Save is refused, with no call, unless the ID on the clicked button is the current candidate ID and the variant matches', () => {
  mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: T0 });
  try {
    const c = armedCard('arm_on_ready', { intent: 'save' });
    for (const ds of [{}, { id: '' }, { id: undefined }, { id: null }]) {
      assert.deepEqual(press(c.el, 'save', { ...click, ...ds }), { sent: false, why: 'Confirm the ID shown on screen first.' }, JSON.stringify(ds));
    }
    for (const id of ['0000000000000000', RID.toLowerCase(), RID.slice(0, 8), `${RID} `, 'A1B2C3D4E5F60718']) {
      const r = press(c.el, 'save', { ...click, id, variant: 'save' });
      assert.deepEqual(r, { sent: false, why: 'The ID on screen changed. Check the new ID, then confirm again.' }, id);
    }
    assert.match(c.el._ui.notice, /The ID on screen changed/);
    assert.equal(press(c.el, 'save', { ...click, id: RID, variant: 'replace_corrupt' }).sent, false, 'a plain candidate is never confirmed with the REPLACE CORRUPT variant');
    assert.equal(c.calls().length, 0);
    // a new candidate (a new Review) while the old panel is still on screen: the old button's ID no longer matches
    mock.timers.tick(5000);
    c.publish('arm_on_ready', { review_id: 'ABCDEF0123456789' });
    assert.equal(press(c.el, 'save', { ...click, id: RID, variant: 'save' }).sent, false);
    assert.equal(c.calls().length, 0);
    assert.equal(press(c.el, 'save', { ...click, id: 'ABCDEF0123456789', variant: 'save' }).sent, true, 'the current ID is confirmed');
    assert.equal(c.calls()[0].data.target_id, 'ABCDEF0123456789');
    c.el.disconnectedCallback();
    // REPLACE CORRUPT: the phrase carries it, and only for a CORRUPT prior
    const k = armedCard('arm_on_corrupt', { intent: 'save' });
    assert.equal(press(k.el, 'save', { ...click, id: 'C0FFEE00C0FFEE01', variant: 'save' }).sent, false, 'a CORRUPT prior needs the REPLACE CORRUPT variant');
    assert.equal(press(k.el, 'save', { ...click, id: 'C0FFEE00C0FFEE01', variant: 'replace_corrupt' }).sent, true);
    assert.deepEqual(k.calls(), [execCall('SAVE', 'C0FFEE00C0FFEE01', 'SAVE C0FFEE00C0FFEE01 REPLACE CORRUPT')]);
    k.el.disconnectedCallback();
  } finally {
    mock.timers.reset();
  }
});

test('FB-B2 Save is refused at click time when the live state no longer supports it, even from a stale screen', () => {
  mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: T0 });
  try {
    const stale = (patch, why, { tickMs = 0 } = {}) => {
      const c = armedCard('arm_on_ready', { intent: 'save' });
      mock.timers.tick(tickMs);
      c.publish('arm_on_ready', patch);
      const r = press(c.el, 'save', { ...click, id: RID, variant: 'save' });
      assert.equal(r.sent, false, JSON.stringify(patch));
      assert.equal(r.why, why, JSON.stringify(patch));
      assert.equal(c.calls().length, 0, JSON.stringify(patch));
      c.el.disconnectedCallback();
    };
    stale({ arm: 'off' }, 'ECCO Fallback Profile Arm is not on');
    stale({ arm: 'unavailable' }, 'The arm entity is unavailable');
    stale({ supervision_stable: 'off' }, 'Home Assistant heartbeat is not stable; wait until the dashboard shows it healthy, then review and save again');
    stale({ ntp_synced: 'off' }, 'clock not NTP-synchronised this boot; the capture time would be untrusted');
    stale({ manual_arm: 'on' }, 'a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first (on now: Manual configuration)');
    stale({ write_lock: 'on' }, 'another inverter transaction is in progress; try again shortly');
    stale({ review: 'st=IDLE;prior=-;exp=-;warn=-;obl=-;latch=-;sv=-', review_id: '-' }, 'no saveable candidate - press Review Current Configuration first');
    stale({ review: scenarios.arm_on_ready.review.replace('prior=VALID', 'prior=UNREADABLE') }, 'Stored profile is UNREADABLE: saving stays disabled until the dongle restarts.');
    // the candidate runs out between render and click
    const c = armedCard('arm_on_ready', { intent: 'save' });
    mock.timers.tick(88_000);
    assert.equal(press(c.el, 'save', { ...click, id: RID, variant: 'save' }).why, 'The candidate is expiring: review again');
    assert.equal(c.calls().length, 0);
    c.el.disconnectedCallback();
    // the arm runs out between render and click (its own 120 s)
    const a = armedCard('arm_on_ready', { intent: 'save' });
    a.publish('arm_on_ready', { review: scenarios.arm_on_ready.review.replace('exp=87', 'exp=120') });
    mock.timers.tick(121_000);
    assert.equal(press(a.el, 'save', { ...click, id: RID, variant: 'save' }).sent, false);
    assert.equal(a.calls().length, 0);
    a.el.disconnectedCallback();
    // a save request is already pending
    const p = armedCard('arm_on_ready', { intent: 'save' });
    assert.equal(press(p.el, 'save', { ...click, id: RID, variant: 'save' }).sent, true);
    assert.equal(press(p.el, 'save', { ...click, id: RID, variant: 'save' }).sent, false);
    assert.equal(p.calls().length, 1);
    p.el.disconnectedCallback();
    // the arm was set for Invalidate: a save from the same arm is refused
    const i = armedCard('arm_on_ready', { intent: 'save' });
    i.el._ui.intent = 'invalidate';
    assert.equal(press(i.el, 'save', { ...click, id: RID, variant: 'save' }).why, 'The arm is set for Invalidate (see the Saved profile card). Turn it off to save instead.');
    assert.equal(i.calls().length, 0);
    i.el.disconnectedCallback();
  } finally {
    mock.timers.reset();
  }
});

test('FB-B2 Cancel: one switch.turn_off on the arm only; the confirmation closes at once and no save goes out meanwhile', () => {
  mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: T0 });
  try {
    const c = armedCard('arm_on_ready', { intent: 'save' });
    c.el._ui.intent = 'save';
    assert.match(c.el._lastRender.cards.c4.inner, /class="confirm"/);
    assert.deepEqual(press(c.el, 'arm-cancel', click), { sent: true });
    assert.deepEqual(c.calls(), [turnOff]);
    assert.doesNotMatch(c.el._lastRender.cards.c4.inner, /class="confirm"|data-act="save"/, 'closed at once, before Home Assistant echoes');
    assert.equal(c.el._ui.intent, null);
    assert.equal(press(c.el, 'save', { ...click, id: RID, variant: 'save' }).why, 'The arm is being turned off');
    assert.equal(c.calls().length, 1);
    // Home Assistant reports the arm off
    mock.timers.tick(200);
    c.publish('ready_match');
    assert.match(c.el._lastRender.cards.c4.inner, /data-act="arm"/);
    assert.equal(c.el._armAnchor, null);
    // cancelling an arm that is not on does nothing
    assert.deepEqual(press(c.el, 'arm-cancel', click), { sent: false, why: 'The arm is not on' });
    assert.equal(c.calls().length, 1);
    c.el.disconnectedCallback();
  } finally {
    mock.timers.reset();
  }
});

test('FB-B2 the confirmation closes by itself: arm off, a new review, the candidate expiring, the arm expiring, a reconfiguration', () => {
  mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: T0 });
  try {
    const open = (c) => /class="confirm"/.test(c.el._lastRender.cards.c4.inner);
    let c = armedCard('arm_on_ready', { intent: 'save' });
    assert.equal(open(c), true);
    c.publish('ready_match');
    assert.equal(open(c), false, 'the arm turned off');
    c.el.disconnectedCallback();
    c = armedCard('arm_on_ready', { intent: 'save' });
    c.publish('reading', { arm: 'off' });
    assert.equal(open(c), false, 'a new review turned the arm off and replaced the candidate');
    c.el.disconnectedCallback();
    c = armedCard('arm_on_ready', { intent: 'save' });
    mock.timers.tick(88_000);
    assert.match(c.el._lastRender.cards.c4.inner, /Candidate is expiring|The candidate is expiring: review again/);
    assert.match(c.el._lastRender.cards.c4.inner, /data-act="save"[^>]*aria-disabled="true"/, 'at zero the Save button is off');
    c.el.disconnectedCallback();
    c = armedCard('arm_on_ready', { intent: 'save' });
    c.publish('expired', { arm: 'on' });
    assert.equal(open(c), false, 'the candidate is gone: no save confirmation; the arm shows as a strip');
    assert.match(c.el._lastRender.cards.c4.inner, /class="armstrip"/);
    c.el.disconnectedCallback();
    c = armedCard('arm_on_ready', { intent: 'save' });
    c.el._ui.intent = 'save';
    c.el._ui.flow = { kind: 'save', state: 'timeout' };
    c.el.setConfig({ type: `custom:${TAG}`, entities: { ...IDS } });
    assert.equal(c.el._ui.intent, null);
    assert.equal(c.el._ui.flow, null);
    c.el.disconnectedCallback();
  } finally {
    mock.timers.reset();
  }
});

test('FB-B2 Invalidate: its own arm and confirmation, the full 16-hex binding, one execute call, no save panel meanwhile', () => {
  mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: T0 });
  try {
    const c = armedCard('idle_saved');
    assert.deepEqual(press(c.el, 'arm-invalidate', click), { sent: true });
    assert.deepEqual(c.calls(), [turnOn]);
    assert.equal(c.el._ui.intent, 'invalidate');
    assert.doesNotMatch(c.el._lastRender.cards.c1.inner, /class="confirm inv"/, 'not optimistic');
    mock.timers.tick(300);
    c.publish('idle_saved', { arm: 'on' }, Date.now(), { arm: Date.now() });
    assert.match(c.el._lastRender.cards.c1.inner, /class="confirm inv"/);
    assert.doesNotMatch(c.el._lastRender.cards.c4.inner, /class="confirm"/);
    // only the full binding, only from this panel
    for (const id of [undefined, '', PID.slice(0, 8), PID.toLowerCase(), '0000000000000000', RID]) {
      assert.equal(press(c.el, 'invalidate', { ...click, id }).sent, false, String(id));
    }
    assert.equal(c.calls().length, 1);
    assert.deepEqual(press(c.el, 'invalidate', { ...click, id: PID }), { sent: true });
    assert.deepEqual(c.calls()[1], execCall('INVALIDATE', PID, `INVALIDATE ${PID}`));
    assert.equal(c.calls().length, 2);
    assert.equal(c.el._ui.flow.kind, 'invalidate');
    assert.match(c.el._lastRender.cards.c1.inner, /Invalidate request sent - waiting for the dongle\./);
    assert.deepEqual(press(c.el, 'invalidate', { ...click, id: PID }).sent, false, 'no double submit');
    assert.deepEqual(c.el._act('review'), { sent: false, why: 'Invalidate in progress' });
    // the dongle answers (arm off, B9 outcome): the request ends and the result is shown in the Saved profile card
    mock.timers.tick(100);
    c.publish('invalidated_ok');
    assert.equal(c.el._ui.flow, null);
    // FB-B2 (CARD-12): the result heading carries tabindex -1 and a focus key
    assert.match(c.el._lastRender.cards.c1.inner, /<div class="at" tabindex="-1" data-fk="act-result-inv">INVALIDATED<\/div>/);
    mock.timers.tick(300_000);
    assert.equal(c.calls().length, 2, 'one arm call and one execute call, nothing else');
    c.el.disconnectedCallback();
  } finally {
    mock.timers.reset();
  }
});

test('FB-B2 Invalidate is refused, with no call, for anything but a VALID profile with a free bus and a matching binding', () => {
  mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: T0 });
  try {
    for (const [patch, why] of [
      [{ profile_state: 'INVALIDATED' }, 'profile is INVALIDATED; only a VALID profile can be invalidated'],
      [{ profile_state: 'PROFILE_STALE' }, 'profile is PROFILE_STALE; only a VALID profile can be invalidated'],
      [{ profile_state: 'SAVE_UNCONFIRMED' }, 'profile is SAVE_UNCONFIRMED; only a VALID profile can be invalidated'],
      [{ write_lock: 'on' }, 'another inverter transaction is in progress; try again shortly'],
      [{ saved_slots: scenarios.idle_saved.saved_slots.replace('b=2BAEBFE9', 'b=11111111') }, 'The saved values on screen do not match the stored profile ID; wait for the dashboard to update'],
      [{ arm: 'off' }, 'ECCO Fallback Profile Arm is not on'],
    ]) {
      const c = armedCard('arm_on_no_candidate');
      c.el._ui.intent = 'invalidate';
      c.publish('arm_on_no_candidate', patch);
      const inv = press(c.el, 'invalidate', { ...click, id: PID });
      assert.equal(inv.sent, false, JSON.stringify(patch));
      assert.equal(inv.why, why, JSON.stringify(patch));
      assert.equal(c.calls().length, 0, JSON.stringify(patch));
      c.el.disconnectedCallback();
    }
    // without the invalidate intent (an arm set elsewhere, a reload) the panel never offers a confirm, and the handler refuses
    const c = armedCard('arm_on_no_candidate');
    assert.doesNotMatch(c.el._lastRender.cards.c1.inner, /class="confirm inv"/);
    assert.equal(press(c.el, 'invalidate', { ...click, id: PID }).sent, false);
    assert.equal(c.calls().length, 0);
    // an invalidate arm is allowed with the supervision, time and other write arms in any state
    const o = armedCard('idle_saved');
    o.publish('idle_saved', { supervision_stable: 'off', supervision_state: 'LOST', ntp_synced: 'off', free_power_arm: 'on' });
    assert.equal(press(o.el, 'arm-invalidate', click).sent, true);
    o.el.disconnectedCallback();
    c.el.disconnectedCallback();
  } finally {
    mock.timers.reset();
  }
});

test('FB-B2 nothing is ever sent from a timer, a render, a state change or a transition: only the five click handlers send', () => {
  mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: T0 });
  try {
    const c = armedCard('arm_on_ready', { intent: 'save' });
    const log = callsOf(c.h);
    // walk every scenario with the arm in each state while time passes and entities change
    for (const name of Object.keys(scenarios)) {
      for (const arm of ['on', 'off']) {
        c.publish(name, { arm }, Date.now(), { arm: Date.now() });
        mock.timers.tick(7000);
      }
    }
    mock.timers.tick(900_000);
    assert.deepEqual(log, [], 'no service call without a click');
    assert.deepEqual(touchedOf(c.h), []);
    c.el.disconnectedCallback();
    assert.equal(c.el._timer, null);
    assert.equal(c.el._flowTimer, null);
    assert.equal(c.el._armPendingTimer, null);
  } finally {
    mock.timers.reset();
  }
});

test('FB-B2 every act in every scenario only ever calls the arm switch or the execute action, with exactly the on-screen values', () => {
  mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: T0 });
  try {
    const allowed = (call, vm) => {
      const d = call.data;
      if (call.domain === 'button' && call.service === 'press') return d.entity_id === IDS.review_button;
      if (call.domain === 'switch' && (call.service === 'turn_on' || call.service === 'turn_off')) return Object.keys(d).join() === 'entity_id' && d.entity_id === ARM;
      if (call.domain === 'esphome' && call.service === EXEC) {
        if (Object.keys(d).sort().join() !== 'action,confirmation,target_id') return false;
        if (d.action === 'SAVE') return d.target_id === vm.reviewId && (d.confirmation === `SAVE ${vm.reviewId}` || (vm.prior === 'CORRUPT' && d.confirmation === `SAVE ${vm.reviewId} REPLACE CORRUPT`));
        return d.action === 'INVALIDATE' && d.target_id === vm.idHex && d.confirmation === `INVALIDATE ${vm.idHex}`;
      }
      return false;
    };
    let sentSomething = 0;
    for (const name of Object.keys(scenarios)) {
      for (const intent of ['save', 'invalidate', null]) {
        const c = armedCard(name);
        c.el._ui.intent = intent;
        const vm = c.el._vm;
        for (const act of ['review', 'arm', 'arm-invalidate', 'arm-cancel', 'save', 'invalidate', 'restore', 'acknowledge', 'noop', undefined]) {
          for (const ds of [{ trusted: true, id: vm.reviewId || vm.idHex || RID, variant: vm.prior === 'CORRUPT' ? 'replace_corrupt' : 'save' }, { trusted: true, id: vm.idHex || RID, variant: 'save' }]) {
            try { press(c.el, act, ds); } catch (e) { /* a refusal is fine */ }
          }
        }
        for (const call of c.calls()) {
          assert.ok(allowed(call, vm), `${name}/${intent}: ${JSON.stringify(call)}`);
          sentSomething += 1;
        }
        assert.deepEqual(touchedOf(c.h), [], `${name}: no hass member outside the five allowed`);
        c.el.disconnectedCallback();
      }
    }
    assert.ok(sentSomething > 20, 'the walk reached the guarded handlers');
  } finally {
    mock.timers.reset();
  }
});

test('FB-B2 timers: the 1 Hz tick runs for the arm countdown, fills the arm placeholder, and stops when the arm turns off', () => {
  mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: T0 });
  try {
    const c = armedCard('arm_on_no_candidate', { armMs: T0 });
    assert.notEqual(c.el._timer, null, 'an arm with no candidate still counts');
    assert.equal(c.el._anchor, null);
    mock.timers.tick(2000);
    const arm = () => c.el._root.timeWrites.filter((w) => w[0] === 'arm').slice(-1)[0][1];
    assert.equal(arm(), '1:58');
    mock.timers.tick(10_000);
    assert.equal(arm(), '1:48');
    // the writes are the placeholders only: no card markup is replaced by a tick
    const writes = () => Object.values(c.el._root.els).reduce((n, e) => n + e.ops.length, 0);
    const before = writes();
    mock.timers.tick(3000);
    assert.equal(writes(), before, 'three ticks, zero markup writes');
    // 120 s later the arm is "expiring" and the tick keeps waiting for the dongle for a while, then stops
    mock.timers.tick(110_000);
    assert.equal(arm(), 'expiring…');
    assert.notEqual(c.el._timer, null);
    mock.timers.tick(61_000);
    assert.equal(c.el._timer, null, 'an arm still reported on after 3 minutes is not counted for ever');
    // the arm turning off ends the tick (no candidate either)
    c.publish('idle_saved');
    assert.equal(c.el._timer, null);
    assert.equal(c.el._armAnchor, null);
    c.el.disconnectedCallback();
  } finally {
    mock.timers.reset();
  }
});

test('FB-B2 disconnecting stops the request and arm timers too', () => {
  mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: T0 });
  try {
    const c = armedCard('ready_match');
    press(c.el, 'arm', click);
    assert.notEqual(c.el._armPendingTimer, null);
    const d = armedCard('arm_on_ready', { intent: 'save' });
    press(d.el, 'save', { ...click, id: RID, variant: 'save' });
    assert.notEqual(d.el._flowTimer, null);
    c.el.disconnectedCallback();
    d.el.disconnectedCallback();
    assert.equal(c.el._armPendingTimer, null);
    assert.equal(d.el._flowTimer, null);
    assert.equal(d.el._timer, null);
    // an Arm press that Home Assistant never echoes: a message, the intent ends, nothing else is sent
    const e = armedCard('ready_match');
    press(e.el, 'arm', click);
    mock.timers.tick(4200);
    assert.equal(e.el._ui.intent, null);
    assert.match(e.el._ui.notice, /The arm did not turn on\. Check the connection and try again\./);
    assert.equal(e.calls().length, 1);
    e.el.disconnectedCallback();
  } finally {
    mock.timers.reset();
  }
});

test('FB-B2 a click that arms moves focus to the confirmation heading, never to the Save button', () => {
  mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: T0 });
  try {
    const c = armedCard('ready_match');
    const focused = [];
    // a root that finds an element by its data-fk only while the current render contains it
    c.el._root.querySelector = (sel) => {
      const key = /data-fk="([^"]+)"/.exec(sel)[1];
      const present = Object.values(c.el._lastRender.cards).some((card) => card.inner.includes(`data-fk="${key}"`));
      return present ? { focus() { focused.push(key); } } : null;
    };
    press(c.el, 'arm', click);
    assert.equal(c.el._focusKey, 'confirm-save-title');
    assert.deepEqual(focused, [], 'the panel does not exist yet: the focus request waits for it');
    c.publish('ready_match', { arm: 'on' }, Date.now(), { arm: Date.now() });
    assert.deepEqual(focused, ['confirm-save-title']);
    assert.equal(c.el._focusKey, null);
    press(c.el, 'arm-cancel', click);
    c.publish('ready_match');
    assert.deepEqual(focused, ['confirm-save-title', 'arm'], 'Cancel puts focus back on Arm Save');
    assert.ok(!focused.includes('save'), 'the Save button is never focused for the operator');
    // a focus request that is never satisfied does not linger
    c.el._focusOn('nothing-here');
    c.el._root.querySelector = () => null;
    mock.timers.tick(9000);
    c.el._renderCards();
    assert.equal(c.el._focusKey, null);
    c.el.disconnectedCallback();
  } finally {
    mock.timers.reset();
  }
});

// ===========================================================================
// FB-B2 card-fix: the findings of the independent safety audit (CARD-03, 04, 05, 06, 08)
// ===========================================================================
const SAVE = { ...click, id: RID, variant: 'save' };
const c4 = (c) => c.el._lastRender.cards.c4.inner;

test('FB-B2 CARD-05: the arm-off echo alone does not end a pending Save; B3 or B9 does at once, the arm only after the grace', () => {
  mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: T0 });
  try {
    // 1. the dongle's first update is only the arm turning off (B3 and B9 follow in later updates)
    let c = armedCard('arm_on_ready', { intent: 'save' });
    mock.timers.tick(1000);
    assert.equal(press(c.el, 'save', SAVE).sent, true);
    mock.timers.tick(200);
    c.publish('arm_on_ready', { arm: 'off' });
    assert.equal(c.el._ui.flow.state, 'sent', 'still waiting for B3 / B9');
    assert.match(c4(c), /class="headline">SAVE REQUESTED</);
    assert.doesNotMatch(c4(c), /data-act="(arm|save|arm-cancel)"|class="confirm"/, 'no Arm Save and no Save: no second submit window');
    assert.deepEqual(press(c.el, 'arm', click), { sent: false, why: 'another Fallback Profile operation is in progress' });
    assert.deepEqual(c.el._act('review'), { sent: false, why: 'Save in progress' });
    assert.equal(c.calls().length, 1);
    mock.timers.tick(100);
    c.publish('saving');
    assert.equal(c.el._ui.flow.state, 'running');
    c.publish('saved_ok');
    assert.equal(c.el._ui.flow, null, 'the outcome ends it');
    c.el.disconnectedCallback();
    // 2. the arm turns off and nothing else is ever published (a repeated identical outcome changes no entity): the grace ends it
    c = armedCard('arm_on_ready', { intent: 'save' });
    mock.timers.tick(1000);
    press(c.el, 'save', SAVE);
    mock.timers.tick(200);
    c.publish('arm_on_ready', { arm: 'off' });
    mock.timers.tick(4000);
    assert.equal(c.el._ui.flow.state, 'sent', 'inside the grace: still pending');
    mock.timers.tick(1000);
    assert.equal(c.el._ui.flow, null, 'the arm stayed off past the grace with nothing else said: the request is over');
    assert.equal(c.calls().length, 1);
    c.el.disconnectedCallback();
    // 3. B9 alone (the arm still reported on) answers at once
    c = armedCard('arm_on_ready', { intent: 'save' });
    press(c.el, 'save', SAVE);
    mock.timers.tick(300);
    c.publish('arm_on_ready', { last_result: 'SAVE REFUSED - something the dongle said' });
    assert.equal(c.el._ui.flow, null);
    c.el.disconnectedCallback();
    // 4. B3 leaving CANDIDATE_READY alone answers at once
    c = armedCard('arm_on_ready', { intent: 'save' });
    press(c.el, 'save', SAVE);
    mock.timers.tick(300);
    c.publish('arm_on_ready', { review: 'st=IDLE;prior=-;exp=-;warn=-;obl=-;latch=-;sv=-', review_id: '-' });
    assert.equal(c.el._ui.flow, null);
    c.el.disconnectedCallback();
    // 5. an invalidate request ends the same way
    c = armedCard('arm_on_no_candidate', { intent: 'invalidate' });
    mock.timers.tick(1000);
    assert.equal(press(c.el, 'invalidate', { ...click, id: PID }).sent, true);
    mock.timers.tick(200);
    c.publish('arm_on_no_candidate', { arm: 'off' });
    assert.equal(c.el._ui.flow.state, 'sent', 'the arm-off echo alone: still pending');
    assert.match(c.el._lastRender.cards.c1.inner, /Invalidate request sent - waiting for the dongle\./);
    mock.timers.tick(6000);
    assert.equal(c.el._ui.flow, null);
    c.el.disconnectedCallback();
  } finally {
    mock.timers.reset();
  }
});

test('FB-B2 CARD-04: after a timeout the confirmation does not come back; a new Save needs the arm off and a new Arm click; Review does not clear the request', () => {
  mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: T0 });
  try {
    const c = armedCard('arm_on_ready', { intent: 'save' });
    mock.timers.tick(1000);
    assert.equal(press(c.el, 'save', SAVE).sent, true);
    assert.equal(c.el._ui.intent, 'sent', 'the attempt used the arm up (the dongle turns it off, even when it refuses)');
    mock.timers.tick(31_000);
    assert.equal(c.el._ui.flow.state, 'timeout');
    // the first request may still be in flight: no confirmation, no Save button; the arm is a strip with a way to turn it off
    assert.doesNotMatch(c4(c), /class="confirm"|data-act="save"|Save Fallback Profile/);
    assert.match(c4(c), /No result yet\. Check Last action before trying again; do not press Save twice\./);
    assert.match(c4(c), /This arm was already used by your request\. Arm timer:/);
    assert.match(c4(c), /Turn arm off<\/button>/);
    // Save is refused whatever a stale button says, and Arm Save is not offered while the arm is on: no second submit under this arm
    assert.deepEqual(press(c.el, 'save', SAVE), { sent: false, why: 'The arm was used by your request. Turn it off and arm again.' });
    assert.deepEqual(press(c.el, 'arm', click), { sent: false, why: 'The arm is already on' });
    assert.equal(c.calls().length, 1);
    // Review does not clear the unanswered request: only the dongle's answer does (B3 changes once it has run the Review)
    assert.equal(c.el._act('review').sent, true);
    assert.equal(c.el._ui.flow.state, 'timeout', 'a Review press is not an answer');
    assert.equal(c.el._ui.intent, 'sent', 'and the arm stays spent');
    assert.doesNotMatch(c4(c), /class="confirm"|data-act="save"/);
    mock.timers.tick(300);
    c.publish('reading', { arm: 'off' });
    assert.equal(c.el._ui.flow, null, 'B3 changed: answered');
    c.el.disconnectedCallback();

    // a new Save in the same situation takes three deliberate clicks: turn the arm off, arm again, confirm
    const d = armedCard('arm_on_ready', { intent: 'save' });
    mock.timers.tick(1000);
    press(d.el, 'save', SAVE);
    mock.timers.tick(31_000);
    assert.equal(d.el._ui.flow.state, 'timeout');
    assert.deepEqual(press(d.el, 'arm-cancel', click), { sent: true });
    mock.timers.tick(100);
    d.publish('arm_on_ready', { arm: 'off' });
    assert.equal(d.el._ui.flow, null, 'the arm is off: the old request is over');
    assert.doesNotMatch(c4(d), /class="confirm"/);
    assert.match(c4(d), /data-act="arm"[^>]*aria-disabled="false"/, 'Arm Save is offered again, with the arm off');
    assert.deepEqual(press(d.el, 'arm', click), { sent: true });
    mock.timers.tick(200);
    d.publish('arm_on_ready', { arm: 'on' }, Date.now(), { arm: Date.now() });
    assert.match(c4(d), /class="confirm"/, 'a fresh arm episode: the confirmation is back');
    assert.deepEqual(press(d.el, 'save', SAVE), { sent: true });
    assert.deepEqual(d.calls().map((x) => `${x.domain}.${x.service}`), [`esphome.${EXEC}`, 'switch.turn_off', 'switch.turn_on', `esphome.${EXEC}`]);
    d.el.disconnectedCallback();

    // an invalidate request is spent the same way
    const i = armedCard('arm_on_no_candidate', { intent: 'invalidate' });
    mock.timers.tick(1000);
    assert.equal(press(i.el, 'invalidate', { ...click, id: PID }).sent, true);
    assert.equal(i.el._ui.intent, 'sent');
    mock.timers.tick(31_000);
    assert.equal(i.el._ui.flow.state, 'timeout');
    assert.doesNotMatch(i.el._lastRender.cards.c1.inner, /class="confirm inv"|data-act="invalidate"/);
    assert.deepEqual(press(i.el, 'invalidate', { ...click, id: PID }), { sent: false, why: 'The arm was used by your request. Turn it off and arm again.' });
    assert.equal(i.calls().filter((x) => x.domain === 'esphome').length, 1);
    i.el.disconnectedCallback();
  } finally {
    mock.timers.reset();
  }
});

test('FB-B2 CARD-04: a rejected call (the request may have reached the dongle) leaves no confirmation either', async () => {
  const c = armedCard('arm_on_ready', { intent: 'save' });
  try {
    let attempts = 0;
    c.h.callService = () => { attempts += 1; return Promise.reject(new Error('rejected')); };
    assert.equal(press(c.el, 'save', SAVE).sent, true);
    await new Promise((r) => setTimeout(r, 5));
    assert.equal(c.el._ui.flow.state, 'unsure');
    assert.equal(c.el._ui.intent, 'sent');
    assert.doesNotMatch(c4(c), /class="confirm"|data-act="save"|Save Fallback Profile/);
    assert.match(c4(c), /may not have reached the dongle/);
    assert.deepEqual(press(c.el, 'save', SAVE), { sent: false, why: 'The arm was used by your request. Turn it off and arm again.' });
    assert.deepEqual(press(c.el, 'arm', click), { sent: false, why: 'The arm is already on' });
    assert.equal(attempts, 1, 'no second request');
  } finally {
    c.el.disconnectedCallback();
  }
});

test('FB-B2 CARD-06: a request pending while the card is detached and attached again still times out', () => {
  mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: T0 });
  try {
    const c = armedCard('arm_on_ready', { intent: 'save' });
    mock.timers.tick(1000);
    press(c.el, 'save', SAVE);
    mock.timers.tick(5000);
    c.el.disconnectedCallback();
    assert.equal(c.el._flowTimer, null, 'detaching stops the timer');
    mock.timers.tick(5000);
    c.el.connectedCallback();
    assert.notEqual(c.el._flowTimer, null, 'attaching arms it again, from the request\'s own send time');
    assert.equal(c.el._ui.flow.state, 'sent');
    mock.timers.tick(20_000);
    assert.equal(c.el._ui.flow.state, 'sent', '30 s after the SEND, not after the re-attach');
    mock.timers.tick(6000);
    assert.equal(c.el._ui.flow.state, 'timeout');
    assert.match(c4(c), /No result yet\./);
    c.el.disconnectedCallback();
    // detached for longer than the window: the first update after attaching evaluates it at once
    const d = armedCard('arm_on_ready', { intent: 'save' });
    press(d.el, 'save', SAVE);
    d.el.disconnectedCallback();
    mock.timers.tick(60_000);
    assert.equal(d.el._ui.flow.state, 'sent', 'nothing evaluates it while it is detached');
    d.el.connectedCallback();
    assert.equal(d.el._ui.flow.state, 'timeout');
    assert.equal(d.el._flowTimer, null, 'a timed-out request needs no timer');
    assert.equal(d.calls().length, 1);
    d.el.disconnectedCallback();
    // a detached card that receives a hass update arms nothing
    const e = armedCard('arm_on_ready', { intent: 'save' });
    press(e.el, 'save', SAVE);
    e.el.disconnectedCallback();
    e.publish('arm_on_ready', { arm: 'off' });
    assert.equal(e.el._flowTimer, null, 'no timer on a detached card');
    e.el.disconnectedCallback();
  } finally {
    mock.timers.reset();
  }
});

test('FB-B2 CARD-08: an arm turned on elsewhere (another tab, a reload) never opens the confirmation and cannot send a Save, whatever the intent', () => {
  mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: T0 });
  try {
    const ELSEWHERE = 'The arm was not turned on from this card. Turn it off and arm again.';
    const SPENT = 'The arm was used by your request. Turn it off and arm again.';
    const FOR_INVALIDATE = 'The arm is set for Invalidate (see the Saved profile card). Turn it off to save instead.';
    for (const [intent, expected] of [[null, ELSEWHERE], ['invalidate', FOR_INVALIDATE], ['sent', SPENT]]) {
      const c = armedCard('arm_on_ready');
      c.el._ui.intent = intent;
      c.el._renderCards();
      assert.doesNotMatch(c4(c), /class="confirm"|data-act="save"|Save Fallback Profile/, `intent ${intent}`);
      assert.deepEqual(press(c.el, 'save', SAVE), { sent: false, why: expected }, `intent ${intent}`);
      assert.equal(c.calls().length, 0, `intent ${intent}`);
      c.el.disconnectedCallback();
    }
    // no intent at all: a strip says so and offers Turn arm off; a normal Arm click then makes the panel
    const c = armedCard('arm_on_ready');
    assert.match(c4(c), /<div class="armstrip" data-act="stay"><span>[^]*Arm was turned on elsewhere\. Arm timer: <span data-t="arm"><\/span><\/span>/);
    assert.deepEqual(press(c.el, 'arm-cancel', click), { sent: true });
    assert.deepEqual(c.calls(), [turnOff]);
    mock.timers.tick(200);
    c.publish('ready_match');
    assert.deepEqual(press(c.el, 'arm', click), { sent: true });
    mock.timers.tick(200);
    c.publish('ready_match', { arm: 'on' }, Date.now(), { arm: Date.now() });
    assert.match(c4(c), /class="confirm"/);
    assert.deepEqual(press(c.el, 'save', SAVE), { sent: true });
    assert.deepEqual(c.calls().map((x) => `${x.domain}.${x.service}`), ['switch.turn_off', 'switch.turn_on', `esphome.${EXEC}`]);
    c.el.disconnectedCallback();
    // an invalidate arm is this card's only when this card switched it on for an invalidate
    for (const [intent, expected] of [[null, ELSEWHERE], ['save', ELSEWHERE], ['sent', SPENT]]) {
      const i = armedCard('arm_on_no_candidate');
      i.el._ui.intent = intent;
      i.el._renderCards();
      assert.doesNotMatch(i.el._lastRender.cards.c1.inner, /class="confirm inv"|data-act="invalidate"/, `intent ${intent}`);
      assert.deepEqual(press(i.el, 'invalidate', { ...click, id: PID }), { sent: false, why: expected }, `intent ${intent}`);
      assert.equal(i.calls().length, 0, `intent ${intent}`);
      i.el.disconnectedCallback();
    }
  } finally {
    mock.timers.reset();
  }
});

test('FB-B2 CARD-03: the arm timer is anchored at the arm switch\'s last_changed; a re-publish of "on" with a new last_changed re-anchors it', () => {
  mock.timers.enable({ apis: ['setInterval', 'setTimeout', 'Date'], now: T0 });
  try {
    const c = armedCard('arm_on_no_candidate', { armMs: T0 });
    assert.equal(c.el._armAnchor.at, T0);
    assert.equal(c.el._armAnchor.exp, 120);
    mock.timers.tick(60_000);
    const arm = () => c.el._root.timeWrites.filter((w) => w[0] === 'arm').slice(-1)[0][1];
    assert.equal(arm(), '1:00');
    // the same state "on", the SAME last_changed: nothing is re-anchored
    c.el.hass = withStates(c.h, statesFor(scenarios.arm_on_no_candidate, T0, null, { arm: T0 }));
    assert.equal(c.el._armAnchor.at, T0);
    // the switch was turned off and on again between two snapshots: the state is still "on", its last_changed is new
    const before = c.el._fp;
    c.el.hass = withStates(c.h, statesFor(scenarios.arm_on_no_candidate, T0, null, { arm: T0 + 60_000 }));
    assert.notEqual(c.el._fp, before, 'a new last_changed alone changes the fingerprint (the card re-renders)');
    assert.equal(c.el._armAnchor.at, T0 + 60_000, 're-anchored at the new last_changed');
    assert.equal(arm(), '2:00', 'the countdown starts again from 2:00');
    c.el.disconnectedCallback();
  } finally {
    mock.timers.reset();
  }
});
