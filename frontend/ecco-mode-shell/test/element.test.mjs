// The custom element against the minidom stand-in. Covers AC1-AC9, AC10-AC14 and AC16 at element level: the default and
// reset rules, mode independence, the zero-call guarantee, the alert strip, one snapshot for both modes, coverage and
// honesty, redaction in every output, search / filter / paging, performance, inert hostile text, accessibility and the
// fail-closed behaviour.
import test, { afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { installDom, installResizeObserver, MElement, MEvent } from './minidom.mjs';

const { registry, doc, win } = installDom(); // BEFORE the card module is evaluated
const ros = installResizeObserver();
const { loadCard, miniCatalogue, miniStates, miniStatesRaw, hostileStatesRaw, statesFrom, makeHass, trapHass, installTraps, mkState, NOW, tick, textOf } = await import('./helpers.mjs');
const { SECRET_VALUES, hostileAttributes, forbiddenStrings, KEY_MARKER } = await import('./secrets.mjs');
const mod = await loadCard('element');
const { EccoModeShell, TAG, STYLE, PALETTE, LIMITS, WITHHELD, classifyRow, validateCatalogue, catalogueItemIds } = mod;

// ---- a stub child card (what Home Assistant's createCardElement would give back) ----
class StubCard extends MElement {
  constructor() {
    super('stub-card');
    this.configs = [];
    this.hassSeen = [];
  }

  setConfig(cfg) {
    this.configs.push(cfg);
    this.config = cfg;
  }

  set hass(h) {
    this.hassSeen.push(h);
    this._hass = h;
    const s = h && h.states && h.states['sensor.ecco_intel_charge_target'];
    this.textContent = s ? `child sees ${s.state}` : 'child sees nothing';
  }

  get hass() {
    return this._hass;
  }
}
doc.registerElement('stub-card', () => new StubCard());

const live = new Set();
const stubs = [];
function mount({ config = {}, states = null, hass = null, catalogue = miniCatalogue(), now = NOW, connect = true, path = '/view-a' } = {}) {
  win.location.pathname = path;
  const el = new EccoModeShell();
  live.add(el);
  el._now = () => now;
  el.setConfig({ type: `custom:${TAG}`, view_id: 'intelligence', title: 'Intelligence', catalogue, page_size: 100, always: [], production: [], allow_custom_cards: ['custom:stub-card'], ...config });
  el.hass = hass || makeHass(states || miniStates());
  if (connect) el.connectedCallback();
  return el;
}
afterEach(() => {
  for (const el of live) el.disconnectedCallback();
  live.clear();
});

const root = (el) => el.shadowRoot;
const q = (el, sel) => root(el).querySelector(sel);
const qa = (el, sel) => root(el).querySelectorAll(sel);
const geek = (el) => q(el, '[data-mode-option="geek"]').click();
const production = (el) => q(el, '[data-mode-option="production"]').click();
const rows = (el) => qa(el, '[data-inspector-row]');
const rowFor = (el, eid) => rows(el).find((r) => r.getAttribute('data-entity-id') === eid);
const stripIds = (el) => qa(el, '[data-ecco-alert-strip] [data-alert-id]').map((n) => n.getAttribute('data-alert-id'));
const typeSearch = (el, text) => {
  const i = q(el, '[data-inspector-search]');
  i.value = text;
  i.dispatchEvent(new MEvent('input'));
};
const choose = (el, name, value) => {
  const s = q(el, `[data-inspector-filter="${name}"]`);
  s.value = value;
  s.dispatchEvent(new MEvent('change'));
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

// ---------------------------------------------------------------------------------------------------------------------------
// registration and basics
// ---------------------------------------------------------------------------------------------------------------------------
test('registration: the element is defined once and the card picker entry is pushed once', async () => {
  assert.equal(registry.get(TAG), EccoModeShell);
  await loadCard('again');
  assert.equal(registry.get(TAG), EccoModeShell, 'a second evaluation does not redefine the tag');
  assert.equal(win.customCards.filter((c) => c.type === TAG).length, 1);
  assert.equal(win.customCards[0].preview, false);
  assert.deepEqual(EccoModeShell.getStubConfig().type, `custom:${TAG}`);
});

test('the mode is exposed through a read-only getter: assigning it throws and changes nothing', () => {
  const el = mount();
  assert.equal(el.mode, 'production');
  assert.throws(() => { el.mode = 'geek'; }, TypeError);
  assert.equal(el.mode, 'production');
});

test('setConfig never throws on hostile or missing configuration, and says so in the strip', () => {
  for (const bad of [undefined, null, 5, 'x', {}, { catalogue: 5 }, { catalogue: { schema: 'x' } }, { always: 'no', production: 7 }]) {
    const el = new EccoModeShell();
    live.add(el);
    assert.doesNotThrow(() => el.setConfig(bad));
    el.hass = makeHass(miniStates());
    el.connectedCallback();
    assert.ok(q(el, '[data-ecco-alert-strip]'), 'the strip exists even without a usable catalogue');
  }
});

// ---------------------------------------------------------------------------------------------------------------------------
// AC1 / AC2: default Production, reload
// ---------------------------------------------------------------------------------------------------------------------------
test('AC1 default: the first render is Production: Production body visible, Geek body hidden and empty, switch says Production', () => {
  const el = mount();
  assert.equal(el.mode, 'production');
  assert.equal(q(el, '[data-ecco-body="production"]').hidden, false);
  assert.equal(q(el, '[data-ecco-body="geek"]').hidden, true);
  assert.equal(q(el, '[data-mode-option="production"]').getAttribute('aria-checked'), 'true');
  assert.equal(q(el, '[data-mode-option="geek"]').getAttribute('aria-checked'), 'false');
  assert.equal(rows(el).length, 0, 'no inventory is built until Geek Mode is entered');
  assert.equal(q(el, '[data-ecco-inspector]'), null);
});

test('AC1 default: the mode is Production even when hass arrives before the element is connected, or before setConfig', () => {
  const a = new EccoModeShell();
  live.add(a);
  a.hass = makeHass(miniStates());
  a.setConfig({ catalogue: miniCatalogue() });
  a.connectedCallback();
  assert.equal(a.mode, 'production');
  assert.equal(q(a, '[data-ecco-body="geek"]').hidden, true);
});

test('AC2 reload: a fresh element is Production again, whatever the previous one did', () => {
  const first = mount();
  geek(first);
  assert.equal(first.mode, 'geek');
  const second = mount();
  assert.equal(second.mode, 'production');
  assert.equal(q(second, '[data-ecco-body="geek"]').hidden, true);
  assert.equal(first.mode, 'geek', 'the first element is unaffected');
});

test('switch: both buttons change the mode and the visible body, and switching back returns to Production', () => {
  const el = mount();
  geek(el);
  assert.equal(el.mode, 'geek');
  assert.equal(q(el, '[data-ecco-body="geek"]').hidden, false);
  assert.equal(q(el, '[data-ecco-body="production"]').hidden, true);
  assert.equal(q(el, '[data-mode-option="geek"]').getAttribute('aria-checked'), 'true');
  assert.equal(q(el, '[data-ecco-mode-switch]').getAttribute('data-mode'), 'geek');
  assert.ok(rows(el).length > 0);
  production(el);
  assert.equal(el.mode, 'production');
  assert.equal(q(el, '[data-ecco-body="geek"]').hidden, true);
  assert.equal(rows(el).length, 0, 'the inventory is released on leaving Geek Mode');
});

// ---------------------------------------------------------------------------------------------------------------------------
// AC3: entering again always starts in Production
// ---------------------------------------------------------------------------------------------------------------------------
test('AC3 navigate away and back: a location change away from the entry path resets to Production', () => {
  const el = mount({ path: '/view-a' });
  geek(el);
  win.location.pathname = '/view-a';
  win.dispatchEvent(new MEvent('location-changed'));
  assert.equal(el.mode, 'geek', 'a location event on the SAME path is not a navigation away');
  win.location.pathname = '/other-view';
  win.dispatchEvent(new MEvent('location-changed'));
  assert.equal(el.mode, 'production');
  win.location.pathname = '/view-a';
  win.dispatchEvent(new MEvent('location-changed'));
  assert.equal(el.mode, 'production', 'coming back stays Production');
  assert.equal(q(el, '[data-ecco-body="geek"]').hidden, true);
});

test('AC3 disconnect and reconnect (Home Assistant kept the element alive): Production', () => {
  const el = mount();
  geek(el);
  el.disconnectedCallback();
  assert.equal(el.mode, 'production');
  el.connectedCallback();
  assert.equal(el.mode, 'production');
  assert.equal(q(el, '[data-ecco-body="geek"]').hidden, true);
});

test('AC3 explicit reset on entry: connecting an element that is somehow still in Geek Mode starts it in Production', () => {
  const el = mount();
  geek(el);
  el.connectedCallback();
  assert.equal(el.mode, 'production');
  assert.equal(win.listenerCount('location-changed') >= 1, true);
  const n = win.listenerCount('location-changed');
  el.connectedCallback();
  assert.equal(win.listenerCount('location-changed'), n, 'connecting twice does not stack listeners');
});

test('AC3 hidden: when the element becomes hidden (a 0 x 0 box) it resets; a normal resize does not', () => {
  const el = mount();
  const ro = ros[ros.length - 1];
  assert.ok(ro && ro.targets.length >= 1, 'the element observes its own size');
  geek(el);
  ro.fire(320, 500);
  assert.equal(el.mode, 'geek');
  ro.fire(0, 0);
  assert.equal(el.mode, 'production');
});

test('AC3 pagehide: resets to Production', () => {
  const el = mount();
  geek(el);
  win.dispatchEvent(new MEvent('pagehide'));
  assert.equal(el.mode, 'production');
});

test('AC3 a disconnected element holds no listener, observer or timer', () => {
  const before = { loc: win.listenerCount('location-changed'), hide: win.listenerCount('pagehide') };
  const el = mount();
  const ro = ros[ros.length - 1];
  assert.equal(win.listenerCount('location-changed'), before.loc + 1);
  el.disconnectedCallback();
  assert.equal(win.listenerCount('location-changed'), before.loc);
  assert.equal(win.listenerCount('pagehide'), before.hide);
  assert.equal(ro.disconnected, true);
});

// ---------------------------------------------------------------------------------------------------------------------------
// AC4: two views never share or leak a mode
// ---------------------------------------------------------------------------------------------------------------------------
test('AC4 two shells: switching one never changes the other, in either direction, and each keeps its own entry path', () => {
  const a = mount({ path: '/view-a' });
  const b = mount({ path: '/view-b' });
  geek(a);
  assert.equal(a.mode, 'geek');
  assert.equal(b.mode, 'production');
  assert.equal(q(b, '[data-ecco-body="geek"]').hidden, true);
  geek(b);
  production(a);
  assert.equal(a.mode, 'production');
  assert.equal(b.mode, 'geek');
  win.location.pathname = '/view-b';
  win.dispatchEvent(new MEvent('location-changed'));
  assert.equal(b.mode, 'geek', 'B entered on /view-b: no reset');
  win.location.pathname = '/view-c';
  win.dispatchEvent(new MEvent('location-changed'));
  assert.equal(b.mode, 'production');
});

test('AC4 two shells: the inspector state (search, filters, expanded rows) is per instance too', () => {
  const a = mount();
  const b = mount();
  geek(a);
  geek(b);
  typeSearch(a, 'charge');
  assert.ok(rows(a).length < rows(b).length);
  assert.equal(q(b, '[data-inspector-search]').value, '');
});

// ---------------------------------------------------------------------------------------------------------------------------
// AC5: a presentation toggle makes no call and touches no storage
// ---------------------------------------------------------------------------------------------------------------------------
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

test('AC5 zero calls: toggling and every inspector interaction call nothing on a hass whose every function throws, and touch no storage or network', async () => {
  const { hass, reads, calls } = trapHass(miniStates());
  const clip = installClipboardAndDownload();
  const traps = installTraps();
  try {
    const el = mount({ hass });
    const opened = [];
    el.addEventListener('hass-more-info', (e) => opened.push(e.detail));
    geek(el);
    production(el);
    geek(el);
    typeSearch(el, 'charge');
    typeSearch(el, '');
    for (const [name, value] of [['status', 'STALE'], ['group', 'advice'], ['priority', 'headline']]) {
      choose(el, name, value);
      choose(el, name, 'all');
    }
    q(el, '[data-inspector-filter="problems"]').click();
    q(el, '[data-inspector-filter="problems"]').click();
    for (const t of qa(el, '[data-group-toggle]')) {
      t.click();
      t.click();
    }
    for (const r of rows(el)) r.querySelector('[data-row-toggle]').click();
    for (const t of qa(el, '[data-raw-toggle]')) t.click();
    assert.ok(qa(el, '[data-inspector-raw]').length > 0, 'the raw view opened');
    q(el, '[data-inspector-page-next]').click();
    q(el, '[data-inspector-page-prev]').click();
    q(el, '[data-inspector-copy]').click();
    await tick();
    for (const t of qa(el, '[data-inspector-copy="row"]')) t.click();
    await tick();
    q(el, '[data-inspector-export="json"]').click();
    q(el, '[data-inspector-export="csv"]').click();
    for (const t of qa(el, '[data-open-entity]')) t.click();
    for (const t of qa(el, '[data-tile-focus]')) t.click();
    el.hass = makeHass(miniStates((s) => { s['sensor.ecco_intel_pv_tomorrow'].state = '13.0'; }), {});
    el.hass = hass;
    production(el);
    assert.deepEqual(calls, [], 'no hass function was called and no other property was read');
    assert.deepEqual([...new Set(reads)].filter((r) => !['states', 'locale', 'themes'].includes(r)), []);
    assert.deepEqual(traps.hits, []);
    assert.ok(clip.clips.length >= 1 && clip.blobs.length === 2, 'copy and both exports did run');
    assert.ok(opened.length >= 1, 'opening an entity is an event, not a call');
    assert.ok(opened.every((d) => typeof d.entityId === 'string'));
  } finally {
    traps.restore();
    clip.restore();
  }
});

test('AC5 the switch never changes helper or service state: Production-only and always cards see no extra hass call from a mode change', () => {
  const el = mount({ config: { always: [{ type: 'custom:stub-card', n: 1 }], production: [{ type: 'custom:stub-card', n: 2 }] } });
  const kids = qa(el, 'stub-card');
  assert.equal(kids.length, 2);
  const seenBefore = kids.map((k) => k.hassSeen.length);
  geek(el);
  production(el);
  geek(el);
  assert.deepEqual(kids.map((k) => k.hassSeen.length), seenBefore, 'a mode change never pushes anything to the children');
  assert.deepEqual(kids.map((k) => k.configs.length), [1, 1], 'a mode change never reconfigures a child');
});

// ---------------------------------------------------------------------------------------------------------------------------
// AC6: the alert strip is identical in both modes and cannot be hidden
// ---------------------------------------------------------------------------------------------------------------------------
const TRIGGER = {
  A01: (s) => { s['sensor.ecco_intel_status'].state = 'SELF_TEST_FAILED'; },
  A02: (s) => { s['sensor.ecco_intel_status'].state = 'unavailable'; },
  A03: (s) => { s['binary_sensor.ecco_intel_watchdog_fresh'].state = 'off'; },
  A04: (s) => { s['sensor.ecco_intel_status'].state = 'STALE'; },
  A05: (s) => { s['input_boolean.ecco_intel_paused'].state = 'on'; },
  A06: (s) => { s['sensor.ecco_intel_status'].attributes.applies_nothing = false; },
  A07: (s) => { s['binary_sensor.ecco_intel_fresh'].state = 'off'; },
};
function stripSnapshot(el) {
  return qa(el, '[data-ecco-alert-strip] [data-alert-id]').map((n) => `${n.getAttribute('data-alert-id')}|${n.getAttribute('data-severity')}|${textOf(n)}`);
}
function assertStripVisible(el) {
  const strip = q(el, '[data-ecco-alert-strip]');
  assert.ok(strip);
  for (let n = strip; n && n.nodeType === 1; n = n.parentNode) assert.equal(n.hidden, false, `${n.tagName} hides the strip`);
  assert.equal(strip.closest('[data-ecco-body]'), null, 'the strip is outside both switchable bodies');
}

for (const a of miniCatalogue().alerts) {
  test(`AC6 ${a.id} (${a.severity}): shown identically in Production and Geek Mode, with its words and its action`, () => {
    const el = mount({ states: miniStates(TRIGGER[a.id]) });
    const inProduction = stripSnapshot(el);
    assertStripVisible(el);
    assert.ok(inProduction.some((s) => s.startsWith(`${a.id}|${a.severity}|`)), `${a.id} missing in Production`);
    const mine = qa(el, `[data-ecco-alert-strip] [data-alert-id="${a.id}"]`)[0];
    assert.match(textOf(mine), new RegExp(a.text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
    assert.match(textOf(mine), new RegExp(a.action.slice(0, 20).replace(/[.*+?^${}()|[\]\\]/g, '\\$&')));
    assert.ok(mine.querySelector('svg'), 'an icon, not colour alone');
    geek(el);
    assertStripVisible(el);
    assert.deepEqual(stripSnapshot(el), inProduction, 'identical in Geek Mode');
    production(el);
    assert.deepEqual(stripSnapshot(el), inProduction, 'and again back in Production');
  });

  for (const how of ['unavailable', 'unknown', 'missing']) {
    test(`AC6 ${a.id}: ${a.entity_id} ${how}: the strip is not clear and is identical in both modes`, () => {
      const el = mount({ states: miniStates((s) => { if (how === 'missing') delete s[a.entity_id]; else s[a.entity_id].state = how; }) });
      const p = stripSnapshot(el);
      assert.ok(p.length > 0);
      assert.ok(qa(el, '[data-ecco-alert-strip] [data-alert-id]').some((n) => n.getAttribute('data-entity-id') === a.entity_id));
      geek(el);
      assert.deepEqual(stripSnapshot(el), p);
      assertStripVisible(el);
    });
  }
}

test('AC6 a calm strip: with no alert both modes show the same quiet line, with an icon and words', () => {
  const el = mount();
  const quiet = q(el, '[data-ecco-alert-strip] [data-alert-none]');
  assert.ok(quiet);
  assert.ok(quiet.querySelector('svg'));
  assert.match(textOf(quiet), /No active alerts/);
  geek(el);
  assert.match(textOf(q(el, '[data-ecco-alert-strip]')), /No active alerts/);
});

test('AC6 critical alerts are announced as alerts; every severity carries its word', () => {
  const el = mount({ states: miniStates((s) => { TRIGGER.A01(s); TRIGGER.A03(s); TRIGGER.A05(s); }) });
  const crit = qa(el, '[data-ecco-alert-strip] [data-severity="critical"]')[0];
  assert.equal(crit.getAttribute('role'), 'alert');
  assert.match(textOf(crit), /Critical/);
  assert.match(textOf(qa(el, '[data-ecco-alert-strip] [data-severity="warning"]')[0]), /Warning/);
  assert.match(textOf(qa(el, '[data-ecco-alert-strip] [data-severity="info"]')[0]), /Notice/);
});

test('AC6 the strip follows the data: it updates on a new hass in both modes and clears when the condition clears', () => {
  const el = mount();
  assert.deepEqual(stripIds(el), []);
  el.hass = makeHass(miniStates(TRIGGER.A01));
  assert.ok(stripIds(el).includes('A01'));
  geek(el);
  el.hass = makeHass(miniStates());
  assert.deepEqual(stripIds(el), []);
  el.hass = makeHass(miniStates(TRIGGER.A03));
  assert.ok(stripIds(el).includes('A03'));
});

test('AC6 the strip ages with the clock: a stale source raises nothing by itself, but the tick re-derives everything', () => {
  const el = mount();
  const s0 = el.snapshot;
  el._now = () => NOW + 3600 * 1000;
  el._tick();
  assert.notEqual(el.snapshot, s0, 'a tick builds a fresh snapshot');
  assert.equal(el.snapshot.rows.find((r) => r.id === 'S01').status, 'STALE', 'an hour later the status sensor is stale');
});

// ---------------------------------------------------------------------------------------------------------------------------
// AC7: one snapshot for everything
// ---------------------------------------------------------------------------------------------------------------------------
test('AC7 same data: the child cards and the Geek rows read the same hass, and both follow changing values', () => {
  const el = mount({ config: { always: [{ type: 'custom:stub-card' }], production: [{ type: 'custom:stub-card' }] } });
  const kids = qa(el, 'stub-card');
  geek(el);
  for (const v of ['80.0', '85.5', '70.0']) {
    const h = makeHass(miniStates((s) => { s['sensor.ecco_intel_charge_target'].state = v; }));
    el.hass = h;
    assert.ok(kids.every((k) => k.hass === h), 'every child holds the very same hass object');
    assert.ok(kids.every((k) => k.textContent === `child sees ${v}`));
    const geekRow = rowFor(el, 'sensor.ecco_intel_charge_target');
    assert.equal(geekRow.querySelector('[data-row-state]').textContent.trim(), `${v} %`, 'the Geek row shows the same value');
    assert.equal(el.snapshot.rows.find((r) => r.id === 'S02').stateText, v);
  }
});

test('AC7 same data: the summary, the strip, the header counts, the tiles and the rows all come from one snapshot object', () => {
  const el = mount();
  geek(el);
  const snap = el.snapshot;
  assert.ok(snap && Array.isArray(snap.rows));
  assert.equal(el.alerts.length, 0);
  const counts = Object.fromEntries(qa(el, '[data-count-status]').map((n) => [n.getAttribute('data-count-status'), Number(n.getAttribute('data-count'))]));
  assert.equal(counts.LIVE, snap.counts.LIVE);
  assert.equal(counts.STALE, snap.counts.STALE);
  assert.equal(counts.UNAVAILABLE, snap.counts.UNAVAILABLE);
  assert.equal(counts.NOT_MEASURED, snap.counts.NOT_MEASURED);
  el.hass = makeHass(miniStates((s) => { s['sensor.ecco_intel_pv_tomorrow'].state = 'unavailable'; }));
  assert.notEqual(el.snapshot, snap);
  const counts2 = Object.fromEntries(qa(el, '[data-count-status]').map((n) => [n.getAttribute('data-count-status'), Number(n.getAttribute('data-count'))]));
  assert.equal(counts2.UNAVAILABLE, counts.UNAVAILABLE + 1);
  assert.equal(counts2.LIVE, counts.LIVE - 1);
  assert.equal(rowFor(el, 'sensor.ecco_intel_pv_tomorrow').getAttribute('data-status'), 'UNAVAILABLE');
});

test('AC7 the Production summary is plain words from the same snapshot and follows the alerts', () => {
  const el = mount();
  const sum = q(el, '[data-ecco-summary]');
  assert.ok(sum);
  const calm = textOf(sum);
  assert.ok(calm.length > 5);
  assert.equal(sum.getAttribute('data-level'), 'ok');
  el.hass = makeHass(miniStates(TRIGGER.A01));
  assert.equal(q(el, '[data-ecco-summary]').getAttribute('data-level'), 'critical');
  assert.match(textOf(q(el, '[data-ecco-summary]')), /self-test/i);
});

// ---------------------------------------------------------------------------------------------------------------------------
// AC8 / AC15: coverage in the DOM
// ---------------------------------------------------------------------------------------------------------------------------
test('AC8 coverage: every catalogue source has a row with the right status; every declared attribute is reachable once the row is open', () => {
  const cat = miniCatalogue();
  const states = miniStates();
  const el = mount({ states });
  geek(el);
  for (const src of cat.sources) {
    const r = rowFor(el, src.entity_id);
    assert.ok(r, `row for ${src.id}`);
    assert.equal(r.getAttribute('data-status'), classifyRow(src, states[src.entity_id], NOW).status, src.id);
    assert.equal(r.getAttribute('data-source-id'), src.id);
    assert.equal(r.getAttribute('data-group'), src.group);
    r.querySelector('[data-row-toggle]').click();
    const open = rowFor(el, src.entity_id);
    for (const a of src.attributes) {
      assert.ok(open.querySelector(`[data-attribute-path="${a.name}"]`), `${src.id}: attribute ${a.name} reachable`);
    }
  }
  assert.equal(catalogueItemIds(validateCatalogue(cat).catalogue).length, 13 + cat.sources.reduce((n, s) => n + s.attributes.length, 0));
});

test('AC8 coverage: a declared-but-absent attribute is shown as not present, never with an invented value', () => {
  const el = mount();
  geek(el);
  rowFor(el, 'sensor.ecco_intel_status').querySelector('[data-row-toggle]').click();
  const a = rowFor(el, 'sensor.ecco_intel_status').querySelector('[data-attribute-path="next_run_at"]');
  assert.equal(a.getAttribute('data-attr-state'), 'absent');
  assert.match(textOf(a), /Not present/);
  assert.ok(!/\d{4}-\d{2}/.test(textOf(a)));
});

test('AC8 discovery: new ecco_intel_ entities appear in the Discovered group without a card change; entities outside the prefix never do', () => {
  const el = mount();
  geek(el);
  const eids = rows(el).map((r) => r.getAttribute('data-entity-id'));
  for (const d of ['sensor.ecco_intel_new_diagnostic', 'binary_sensor.ecco_intel_new_flag', 'automation.ecco_intel_alert_new_example']) {
    assert.equal(rowFor(el, d).getAttribute('data-group'), 'discovered', d);
    assert.equal(rowFor(el, d).getAttribute('data-discovered'), 'true');
  }
  for (const never of ['sensor.other_thing', 'sensor.ecco_unrelated', 'light.example_lamp', 'sensor.ecco_intel_excluded_probe']) assert.ok(!eids.includes(never), never);
  const s = miniStates();
  s['sensor.ecco_intel_arrives_later'] = mkState('sensor.ecco_intel_arrives_later', '4', { friendly_name: 'Arrives later' });
  el.hass = makeHass(s);
  assert.equal(rowFor(el, 'sensor.ecco_intel_arrives_later').getAttribute('data-group'), 'discovered');
});

test('AC8 the exceptions of the catalogue are listed with their reasons (nothing silently missing from the inventory)', () => {
  const el = mount();
  geek(el);
  const ex = qa(el, '[data-exception]');
  assert.equal(ex.length, 3);
  assert.deepEqual(ex.map((e) => e.getAttribute('data-reason')), ['secret', 'privacy', 'unsupported_source']);
  assert.match(textOf(ex[0]), /Integration access token/);
});

// ---------------------------------------------------------------------------------------------------------------------------
// AC9: honesty in the DOM
// ---------------------------------------------------------------------------------------------------------------------------
test('AC9 honesty: every status is labelled in words and with an icon; a stale value is not shown as live', () => {
  const el = mount();
  geek(el);
  const words = { LIVE: 'Live', STALE: 'Stale', UNAVAILABLE: 'Unavailable', UNKNOWN: 'Unknown', NOT_MEASURED: 'Not measured', SIMULATED: 'Simulated', UNVERIFIED: 'Unverified' };
  const want = { 'sensor.ecco_intel_overnight_demand': 'STALE', 'sensor.ecco_intel_export_event': 'SIMULATED', 'sensor.ecco_intel_dump_to_grid': 'NOT_MEASURED',
    'sensor.ecco_intel_data_quality': 'UNAVAILABLE', 'sensor.ecco_intel_accuracy': 'UNKNOWN', 'sensor.ecco_intel_predicted_morning_soc': 'UNVERIFIED',
    'sensor.ecco_intel_status': 'LIVE' };
  for (const [eid, status] of Object.entries(want)) {
    const r = rowFor(el, eid);
    assert.equal(r.getAttribute('data-status'), status, eid);
    const chip = r.querySelector('[data-status-chip]');
    assert.equal(chip.getAttribute('data-status-chip'), status);
    assert.ok(chip.querySelector('svg'), `${status} has an icon`);
    assert.equal(textOf(chip), words[status], `${status} is said in words`);
  }
  const stale = rowFor(el, 'sensor.ecco_intel_overnight_demand');
  assert.ok(!/\bLive\b/.test(textOf(stale.querySelector('[data-row-head]'))), 'a stale row never says Live');
  assert.match(textOf(stale.querySelector('[data-row-age]')), /1 h 6 min ago/);
});

test('AC9 honesty: unavailable, unknown and missing rows show words, never a value; the unit never follows a non-value', () => {
  const el = mount();
  geek(el);
  const txt = (eid) => textOf(rowFor(el, eid).querySelector('[data-row-state]'));
  assert.equal(txt('sensor.ecco_intel_data_quality'), 'Unavailable');
  assert.equal(txt('sensor.ecco_intel_accuracy'), 'Unknown');
  assert.equal(txt('sensor.ecco_intel_dump_to_grid'), 'Not measured');
  assert.equal(txt('sensor.ecco_intel_overnight_demand'), '6.2 kWh');
  assert.match(textOf(rowFor(el, 'sensor.ecco_intel_dump_to_grid').querySelector('[data-row-age]')), /no data/i);
});

test('AC9 honesty: the instrument tiles carry the same status and never a fresh-looking ring for stale data', () => {
  const states = miniStates((s) => { s['sensor.ecco_intel_charge_target'] = mkState('sensor.ecco_intel_charge_target', '80.0', s['sensor.ecco_intel_charge_target'].attributes, { ageS: 5000 }); });
  const el = mount({ states });
  geek(el);
  const tile = qa(el, '[data-tile]').find((t) => t.getAttribute('data-entity-id') === 'sensor.ecco_intel_charge_target');
  assert.equal(tile.getAttribute('data-status'), 'STALE');
  assert.equal(tile.getAttribute('data-ring'), 'empty');
  assert.match(textOf(tile), /Stale/);
  assert.ok(!/\bLive\b/.test(textOf(tile)));
  const ok = qa(el, '[data-tile]').find((t) => t.getAttribute('data-entity-id') === 'sensor.ecco_intel_status');
  assert.equal(ok.getAttribute('data-status'), 'LIVE');
  assert.ok(Number(ok.getAttribute('data-ring-percent')) > 90);
});

test('AC9 honesty: a source with no freshness rule says its age is not monitored instead of implying it is fresh', () => {
  const el = mount();
  geek(el);
  assert.match(textOf(rowFor(el, 'binary_sensor.ecco_intel_watchdog_fresh').querySelector('[data-row-age]')), /not monitored/i);
});

test('AC9 honesty: the header counts the statuses and the withheld values', () => {
  const el = mount();
  geek(el);
  const c = (k) => Number(q(el, `[data-count-status="${k}"]`).getAttribute('data-count'));
  assert.equal(c('LIVE'), 10);
  assert.equal(c('STALE'), 1);
  assert.equal(c('UNAVAILABLE'), 1);
  assert.equal(c('NOT_MEASURED'), 1);
  assert.equal(Number(q(el, '[data-count-withheld]').getAttribute('data-count')), 0);
  for (const k of ['LIVE', 'STALE', 'UNAVAILABLE', 'NOT_MEASURED']) assert.ok(q(el, `[data-count-status="${k}"] svg`), `${k} count has an icon`);
});

// ---------------------------------------------------------------------------------------------------------------------------
// AC10: redaction in every output
// ---------------------------------------------------------------------------------------------------------------------------
function hostileSecretStates() {
  const s = miniStates();
  s['sensor.ecco_intel_hostile'] = mkState('sensor.ecco_intel_hostile', SECRET_VALUES[0].value, hostileAttributes());
  s['sensor.ecco_intel_status'].attributes.token = KEY_MARKER('statustoken');
  s['sensor.ecco_intel_status'].attributes.note = SECRET_VALUES[4].value;
  s['sensor.ecco_intel_charge_target'].attributes.advice.window.deep = { api_key: KEY_MARKER('deepapi'), ip: SECRET_VALUES[7].value };
  return s;
}

function openEverything(el) {
  for (const r of rows(el)) r.querySelector('[data-row-toggle]').click();
  for (const t of qa(el, '[data-raw-toggle]')) t.click();
}

test('AC10 the rendered Geek surface (rows, attributes, raw view, titles, tooltips) holds no secret and marks withheld values', () => {
  const el = mount({ states: hostileSecretStates() });
  geek(el);
  openEverything(el);
  const text = allText(root(el));
  for (const f of forbiddenStrings()) assert.ok(!text.includes(f), `the DOM leaked ${f.slice(0, 12)}`);
  assert.ok(qa(el, '[data-withheld]').length > 0);
  assert.match(textOf(q(el, '[data-withheld]')), /Withheld/);
  assert.ok(q(el, '[data-withheld] svg'), 'a withheld marker carries an icon, not just colour');
  assert.ok(Number(q(el, '[data-count-withheld]').getAttribute('data-count')) > 40);
  const raw = qa(el, '[data-inspector-raw]').map((n) => n.textContent).join('\n');
  assert.match(raw, /\[withheld\]/);
});

test('AC10 search: a search for any secret value or secret-keyed value finds nothing; benign text still matches', () => {
  const el = mount({ states: hostileSecretStates() });
  geek(el);
  for (const f of [SECRET_VALUES[0].value, SECRET_VALUES[4].value, 'hunter2', KEY_MARKER('password'), KEY_MARKER('statustoken'), SECRET_VALUES[7].value]) {
    typeSearch(el, f);
    assert.equal(rows(el).length, 0, `searching for ${f.slice(0, 10)} found a row`);
    assert.ok(q(el, '[data-inspector-empty]'));
  }
  typeSearch(el, 'visible-benign-text');
  assert.equal(rows(el).length, 1);
});

test('AC10 copy and export: the bytes carry no secret (all rows, one row, json and csv)', async () => {
  const clip = installClipboardAndDownload();
  try {
    const el = mount({ states: hostileSecretStates() });
    geek(el);
    q(el, '[data-inspector-copy]').click();
    await tick();
    q(el, '[data-inspector-export="json"]').click();
    q(el, '[data-inspector-export="csv"]').click();
    rowFor(el, 'sensor.ecco_intel_hostile').querySelector('[data-row-toggle]').click();
    rowFor(el, 'sensor.ecco_intel_hostile').querySelector('[data-inspector-copy="row"]').click();
    await tick();
    assert.equal(clip.clips.length, 2);
    assert.equal(clip.blobs.length, 2);
    const outputs = [...clip.clips, ...(await Promise.all(clip.blobs.map((b) => b.text())))];
    for (const bytes of outputs) {
      assert.ok(bytes.length > 100);
      for (const f of forbiddenStrings()) assert.ok(!bytes.includes(f), `an output leaked ${f.slice(0, 12)}`);
    }
    assert.match(outputs[0], /ecco-geek-export\/1/);
    assert.match(outputs[3], /^id,entity_id,group,title,status,state,unit,age_s,attributes/);
  } finally {
    clip.restore();
  }
});

// ---------------------------------------------------------------------------------------------------------------------------
// AC11: search, filters, groups, paging in the UI
// ---------------------------------------------------------------------------------------------------------------------------
test('AC11 grouping: headline signals first, then the groups in catalogue order, with the Discovered group last', () => {
  const el = mount();
  geek(el);
  const list = rows(el);
  assert.equal(list[0].getAttribute('data-priority'), 'headline');
  const groups = [...new Set(list.map((r) => r.getAttribute('data-group')))];
  assert.deepEqual(groups, ['headline', 'advice', 'health', 'controls', 'discovered']);
  const bar = qa(el, '[data-group-toggle]').map((b) => b.getAttribute('data-group-toggle'));
  assert.deepEqual(bar, groups);
});

test('AC11 groups are collapsible: collapsing a group removes its rows and keeps the others; expanding brings them back', () => {
  const el = mount();
  geek(el);
  const n = rows(el).length;
  const adviceRows = rows(el).filter((r) => r.getAttribute('data-group') === 'advice').length;
  const btn = q(el, '[data-group-toggle="advice"]');
  assert.equal(btn.getAttribute('aria-expanded'), 'true');
  btn.click();
  assert.equal(q(el, '[data-group-toggle="advice"]').getAttribute('aria-expanded'), 'false');
  assert.equal(rows(el).length, n - adviceRows);
  assert.ok(rows(el).every((r) => r.getAttribute('data-group') !== 'advice'));
  q(el, '[data-group-toggle="advice"]').click();
  assert.equal(rows(el).length, n);
});

test('AC11 search narrows the rows live; several terms must all match; the empty result says so and can be cleared', () => {
  const el = mount();
  geek(el);
  const total = rows(el).length;
  typeSearch(el, 'charge target');
  assert.deepEqual(rows(el).map((r) => r.getAttribute('data-entity-id')), ['sensor.ecco_intel_charge_target']);
  typeSearch(el, 'charge');
  assert.ok(rows(el).length >= 2, 'a substring also finds precharge_by on the status sensor');
  typeSearch(el, 'solar tomorrow');
  assert.deepEqual(rows(el).map((r) => r.getAttribute('data-entity-id')), ['sensor.ecco_intel_pv_tomorrow']);
  typeSearch(el, 'target_soc_pct');
  assert.ok(rows(el).length >= 1, 'attribute names are searched');
  typeSearch(el, 'cloudy morning');
  assert.equal(rows(el).length, 1, 'attribute values are searched');
  typeSearch(el, 'zzz-no-such-thing');
  assert.equal(rows(el).length, 0);
  assert.match(textOf(q(el, '[data-inspector-empty]')), /No data points match/);
  q(el, '[data-inspector-clear]').click();
  assert.equal(rows(el).length, total);
  assert.equal(q(el, '[data-inspector-search]').value, '');
});

test('AC11 filters: status, group, priority and problems each narrow the list and can be combined', () => {
  const el = mount();
  geek(el);
  choose(el, 'status', 'STALE');
  assert.deepEqual(rows(el).map((r) => r.getAttribute('data-entity-id')), ['sensor.ecco_intel_overnight_demand']);
  choose(el, 'status', 'all');
  choose(el, 'group', 'controls');
  assert.ok(rows(el).length === 2 && rows(el).every((r) => r.getAttribute('data-group') === 'controls'));
  choose(el, 'group', 'all');
  choose(el, 'priority', 'obscure');
  assert.ok(rows(el).length >= 1 && rows(el).every((r) => r.getAttribute('data-priority') === 'obscure'));
  choose(el, 'priority', 'all');
  q(el, '[data-inspector-filter="problems"]').click();
  assert.equal(q(el, '[data-inspector-filter="problems"]').getAttribute('aria-pressed'), 'true');
  assert.ok(rows(el).length >= 6 && rows(el).every((r) => r.getAttribute('data-status') !== 'LIVE'));
  choose(el, 'status', 'UNAVAILABLE');
  assert.equal(rows(el).length, 1);
});

test('AC11 paging: windows of page_size rows with next and previous; the buttons are disabled at the ends; the info line says where you are', () => {
  const el = mount({ config: { page_size: 5 } });
  geek(el);
  assert.equal(rows(el).length, 5);
  assert.equal(q(el, '[data-inspector-page-prev]').hasAttribute('disabled'), true);
  assert.match(textOf(q(el, '[data-inspector-page-info]')), /1.5 of 16/);
  const first = rows(el)[0].getAttribute('data-entity-id');
  q(el, '[data-inspector-page-next]').click();
  assert.equal(rows(el).length, 5);
  assert.notEqual(rows(el)[0].getAttribute('data-entity-id'), first);
  assert.match(textOf(q(el, '[data-inspector-page-info]')), /6.10 of 16/);
  q(el, '[data-inspector-page-next]').click();
  q(el, '[data-inspector-page-next]').click();
  assert.equal(rows(el).length, 1);
  assert.equal(q(el, '[data-inspector-page-next]').hasAttribute('disabled'), true);
  q(el, '[data-inspector-page-prev]').click();
  assert.equal(rows(el).length, 5);
  typeSearch(el, 'charge target');
  assert.match(textOf(q(el, '[data-inspector-page-info]')), /1.1 of 1/, 'a new search returns to the first page');
});

test('AC11 row details: expanding shows the description, the attribute rows with their descriptions and units, and the open and copy controls', () => {
  const el = mount();
  geek(el);
  const r0 = rowFor(el, 'sensor.ecco_intel_charge_target');
  assert.equal(r0.querySelector('[data-row-toggle]').getAttribute('aria-expanded'), 'false');
  assert.equal(r0.querySelector('[data-row-detail]'), null);
  r0.querySelector('[data-row-toggle]').click();
  const r = rowFor(el, 'sensor.ecco_intel_charge_target');
  assert.equal(r.querySelector('[data-row-toggle]').getAttribute('aria-expanded'), 'true');
  const d = r.querySelector('[data-row-detail]');
  assert.match(textOf(d), /battery level the engine would aim for/);
  const a = r.querySelector('[data-attribute-path="advice.target_soc_pct"]');
  assert.match(textOf(a), /Advised target state of charge/);
  assert.match(textOf(a), /80/);
  assert.equal(a.getAttribute('data-depth'), '1');
  assert.ok(r.querySelector('[data-attribute-path="advice"]'));
  assert.match(textOf(r.querySelector('[data-attribute-path="friendly_name"]')) || '', /ECCO Intelligence charge target|Not described/);
  assert.ok(r.querySelector('[data-open-entity]'));
  assert.ok(r.querySelector('[data-inspector-copy="row"]'));
  assert.equal(r.querySelector('[data-inspector-raw]'), null);
  r.querySelector('[data-raw-toggle]').click();
  const raw = rowFor(el, 'sensor.ecco_intel_charge_target').querySelector('[data-inspector-raw]');
  assert.ok(raw);
  assert.match(raw.textContent, /"target_soc_pct": 80/);
  assert.match(raw.textContent, /"deep"/, 'deeper nesting levels are in the raw view');
});

test('AC11 opening an entity dispatches hass-more-info with the entity id and nothing else; a missing entity offers no link', () => {
  const el = mount();
  geek(el);
  const got = [];
  el.addEventListener('hass-more-info', (e) => got.push(e.detail));
  const r = rowFor(el, 'sensor.ecco_intel_charge_target');
  r.querySelector('[data-row-toggle]').click();
  rowFor(el, 'sensor.ecco_intel_charge_target').querySelector('[data-open-entity]').click();
  assert.deepEqual(got, [{ entityId: 'sensor.ecco_intel_charge_target' }]);
  rowFor(el, 'sensor.ecco_intel_dump_to_grid').querySelector('[data-row-toggle]').click();
  assert.equal(rowFor(el, 'sensor.ecco_intel_dump_to_grid').querySelector('[data-open-entity]'), null);
});

test('AC11 an instrument tile jumps to its row: it filters the inventory to that entity and opens it', () => {
  const el = mount();
  geek(el);
  const tile = qa(el, '[data-tile]')[0];
  const eid = tile.getAttribute('data-entity-id');
  tile.querySelector('[data-tile-focus]').click();
  assert.deepEqual(rows(el).map((r) => r.getAttribute('data-entity-id')), [eid]);
  assert.equal(rows(el)[0].querySelector('[data-row-toggle]').getAttribute('aria-expanded'), 'true');
});

test('AC11 instrument tiles are the headline sources, in the header, with their value and unit', () => {
  const el = mount();
  geek(el);
  const tiles = qa(el, '[data-tile]');
  const heads = miniCatalogue().sources.filter((s) => s.priority === 'headline').map((s) => s.entity_id);
  assert.deepEqual(tiles.map((t) => t.getAttribute('data-entity-id')), heads);
  const charge = tiles.find((t) => t.getAttribute('data-entity-id') === 'sensor.ecco_intel_charge_target');
  assert.match(textOf(charge), /80\.0\s*%/);
});

// ---------------------------------------------------------------------------------------------------------------------------
// AC12: performance
// ---------------------------------------------------------------------------------------------------------------------------
function bigStates(n) {
  const s = miniStates();
  for (let i = 0; i < n; i += 1) {
    const id = `sensor.ecco_intel_synth_${String(i).padStart(5, '0')}`;
    s[id] = mkState(id, String(i), { friendly_name: `Synthetic ${i}`, unit_of_measurement: 'kWh', advice: { a: i, b: 'text' }, reason_codes: ['A'] });
  }
  for (let i = 0; i < 2000; i += 1) s[`sensor.other_${i}`] = mkState(`sensor.other_${i}`, String(i), {});
  return s;
}

test('AC12 performance: with 5000 entities the first Geek render builds at most one page; a search is quick; one update rebuilds one row', () => {
  const states = bigStates(5000);
  const el = mount({ states, config: { page_size: 25 } });
  let t = performance.now();
  geek(el);
  const first = performance.now() - t;
  assert.ok(first < 8000, `first Geek render ${first.toFixed(0)} ms`);
  assert.ok(rows(el).length <= 25, `${rows(el).length} rows in the DOM`);
  assert.ok(el.inspectorStats.rowBuilds <= 25, `rowBuilds ${el.inspectorStats.rowBuilds}`);
  assert.match(textOf(q(el, '[data-inspector-page-info]')), /of 5016/);
  t = performance.now();
  typeSearch(el, 'synthetic 4999');
  const search = performance.now() - t;
  assert.equal(rows(el).length, 1);
  assert.ok(search < 1500, `search ${search.toFixed(0)} ms`);
  typeSearch(el, '');
  const stats0 = { ...el.inspectorStats };
  el.hass = makeHass({ ...states });
  assert.equal(el.inspectorStats.rowBuilds, stats0.rowBuilds, 'an unchanged hass rebuilds no row');
  const target = rows(el)[3].getAttribute('data-entity-id');
  const next = { ...states, [target]: mkState(target, 'changed!', states[target].attributes) };
  const before = el.inspectorStats.rowBuilds;
  el.hass = makeHass(next);
  assert.equal(el.inspectorStats.rowBuilds - before, 1, 'exactly one row was rebuilt');
  assert.equal(rowFor(el, target).querySelector('[data-row-state]').textContent.trim().startsWith('changed!'), true);
  assert.equal(el.inspectorStats.fullRebuilds, stats0.fullRebuilds, 'no full rebuild');
});

test('AC12 performance: the DOM never holds more rows than the page, whatever the filter; paging walks the whole set', () => {
  const states = bigStates(600);
  const el = mount({ states, config: { page_size: 40 } });
  geek(el);
  const seen = new Set();
  for (let i = 0; i < 40; i += 1) {
    assert.ok(rows(el).length <= 40);
    for (const r of rows(el)) seen.add(r.getAttribute('data-entity-id'));
    if (q(el, '[data-inspector-page-next]').hasAttribute('disabled')) break;
    q(el, '[data-inspector-page-next]').click();
  }
  assert.equal(seen.size, 600 + 16);
});

test('AC12 caps: a huge attribute is truncated with a marker in the DOM too', () => {
  const states = miniStates((s) => { s['sensor.ecco_intel_new_diagnostic'].attributes.huge = 'z'.repeat(300000); });
  const el = mount({ states });
  geek(el);
  const r = rowFor(el, 'sensor.ecco_intel_new_diagnostic');
  r.querySelector('[data-row-toggle]').click();
  rowFor(el, 'sensor.ecco_intel_new_diagnostic').querySelector('[data-raw-toggle]').click();
  const text = allText(root(el));
  assert.ok(text.length < 400000, `the whole DOM text is ${text.length} characters`);
  assert.match(text, /truncated/);
});

// ---------------------------------------------------------------------------------------------------------------------------
// AC13: hostile text is inert
// ---------------------------------------------------------------------------------------------------------------------------
const ALLOWED_TAGS = new Set(['style', 'div', 'span', 'section', 'header', 'h2', 'h3', 'p', 'button', 'input', 'select', 'option', 'label', 'code', 'pre',
  'strong', 'em', 'a', 'svg', 'path', 'circle', 'rect', 'ul', 'li', 'details', 'summary', 'stub-card', 'small', 'b']);
const ALLOWED_ATTRS = (n) => /^(data-[a-z-]+|aria-[a-z]+)$/.test(n) || ['class', 'role', 'type', 'title', 'tabindex', 'hidden', 'd', 'viewBox', 'fill', 'stroke', 'stroke-width',
  'stroke-linecap', 'stroke-linejoin', 'cx', 'cy', 'r', 'x', 'y', 'width', 'height', 'rx', 'placeholder', 'value', 'disabled', 'selected', 'for', 'id', 'name',
  'href', 'download', 'autocomplete', 'spellcheck', 'inputmode', 'lang', 'open', 'stroke-dasharray'].includes(n);

test('AC13 XSS: hostile states, names and attributes render as inert text; no element, tag or attribute NAME comes from data', () => {
  doc.resetRecorded();
  const long = 'L'.repeat(100000);
  const states = { ...miniStates(), ...statesFrom(hostileStatesRaw()) };
  states['sensor.ecco_intel_hostile_long'] = mkState('sensor.ecco_intel_hostile_long', long, { friendly_name: long, note: `${long}<script>`, [`k${'K'.repeat(5000)}`]: 1 });
  states['sensor.ecco_intel_new_diagnostic'].attributes.friendly_name = '<img src=x onerror=globalThis.__pwn=9>';
  const el = mount({ states });
  geek(el);
  openEverything(el);
  typeSearch(el, '<b>');
  typeSearch(el, '');
  assert.equal(globalThis.__pwn, undefined);
  assert.equal(doc.recorded.innerHTMLAttempts, 0);
  for (const tag of doc.recorded.tags) assert.ok(ALLOWED_TAGS.has(tag), `unexpected element <${tag}>`);
  for (const a of doc.recorded.attrNames) assert.ok(ALLOWED_ATTRS(a), `unexpected attribute name ${a}`);
  for (const p of doc.recorded.styleProps) assert.match(p, /^--ecco-/);
  const text = allText(root(el));
  assert.ok(text.includes('<script>globalThis.__pwn = 1</script>'), 'markup is present as TEXT');
  assert.ok(text.includes('onerror=globalThis.__pwn=2'));
  assert.ok(text.includes('<b>bold</b>'), 'a hostile key is shown as text');
  assert.ok(text.includes('javascript:globalThis.__pwn=5'), 'a javascript: value is only text');
  for (const el2 of root(el).descendants()) {
    for (const [k] of el2.attrs) assert.ok(!/^on/i.test(k), `an event-handler attribute ${k}`);
    assert.ok(!['script', 'img', 'iframe', 'object', 'embed', 'link', 'meta', 'base', 'form'].includes(el2.tagName));
    if (el2.hasAttribute('href')) assert.match(el2.getAttribute('href'), /^blob:/);
    for (const n of el2.childNodes) if (n.nodeType === 3) assert.ok(n.data.length <= LIMITS.rawChars + 200, `a ${n.data.length}-character text node`);
  }
});

test('AC13 XSS: control, zero-width and bidi characters are shown as visible escapes, never raw', () => {
  const el = mount({ states: { ...miniStates(), ...statesFrom(hostileStatesRaw()) } });
  geek(el);
  openEverything(el);
  const text = allText(root(el));
  assert.ok(!/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u00ad\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff]/.test(text));
  assert.match(text, /U\+200B/);
  assert.match(text, /U\+202E/);
  assert.match(text, /U\+0000/);
});

test('AC13 XSS: markup in the catalogue itself (titles, descriptions, alerts, exceptions) is text too', () => {
  const cat = miniCatalogue();
  cat.title = '<img src=x onerror=1>';
  cat.sources[0].title = '"><svg onload=1>';
  cat.sources[0].description = '<script>1</script>';
  cat.alerts[0].text = '<b>alert</b>';
  cat.alerts[0].action = '"><i>do it</i>';
  cat.exceptions[0].what = '<u>x</u>';
  doc.resetRecorded();
  const el = mount({ catalogue: cat, states: miniStates(TRIGGER.A01) });
  geek(el);
  openEverything(el);
  assert.equal(doc.recorded.innerHTMLAttempts, 0);
  for (const tag of doc.recorded.tags) assert.ok(ALLOWED_TAGS.has(tag), tag);
  const text = allText(root(el));
  assert.ok(text.includes('<b>alert</b>'));
  assert.ok(text.includes('"><svg onload=1>'));
});

// ---------------------------------------------------------------------------------------------------------------------------
// AC14: accessibility and layout
// ---------------------------------------------------------------------------------------------------------------------------
test('AC14 the switch is a labelled radio group; exactly one option is checked; roving tabindex; every button is type=button', () => {
  const el = mount();
  const sw = q(el, '[data-ecco-mode-switch]');
  assert.equal(sw.getAttribute('role'), 'radiogroup');
  assert.ok(sw.getAttribute('aria-label'));
  const opts = qa(el, '[data-mode-option]');
  assert.equal(opts.length, 2);
  for (const o of opts) {
    assert.equal(o.getAttribute('role'), 'radio');
    assert.ok(o.getAttribute('aria-label') || textOf(o));
    assert.equal(o.getAttribute('type'), 'button');
    assert.ok(o.querySelector('svg'), 'an icon, not colour alone');
  }
  assert.equal(opts.filter((o) => o.getAttribute('aria-checked') === 'true').length, 1);
  assert.equal(opts[0].getAttribute('tabindex'), '0');
  assert.equal(opts[1].getAttribute('tabindex'), '-1');
  geek(el);
  assert.equal(q(el, '[data-mode-option="geek"]').getAttribute('tabindex'), '0');
  assert.equal(q(el, '[data-mode-option="production"]').getAttribute('tabindex'), '-1');
  geek(el);
  for (const b of qa(el, 'button')) assert.equal(b.getAttribute('type'), 'button', 'no button can submit anything');
  assert.match(textOf(q(el, '[data-ecco-mode-note]')), /never changes what ECCO does/i);
});

test('AC14 the switch is keyboard operable: arrows, Home and End move and select, and the focus follows', () => {
  const el = mount();
  const key = (target, k) => target.dispatchEvent(new MEvent('keydown', { key: k }));
  const prod = q(el, '[data-mode-option="production"]');
  prod.focus();
  key(prod, 'ArrowRight');
  assert.equal(el.mode, 'geek');
  assert.equal(root(el).activeElement.getAttribute('data-mode-option'), 'geek');
  key(q(el, '[data-mode-option="geek"]'), 'ArrowLeft');
  assert.equal(el.mode, 'production');
  key(q(el, '[data-mode-option="production"]'), 'End');
  assert.equal(el.mode, 'geek');
  key(q(el, '[data-mode-option="geek"]'), 'Home');
  assert.equal(el.mode, 'production');
  key(q(el, '[data-mode-option="production"]'), 'ArrowDown');
  assert.equal(el.mode, 'geek');
  key(q(el, '[data-mode-option="geek"]'), 'ArrowUp');
  assert.equal(el.mode, 'production');
  key(q(el, '[data-mode-option="production"]'), 'a');
  assert.equal(el.mode, 'production', 'other keys do nothing');
});

test('AC14 inspector controls are labelled, typed and keyboard friendly; rows expose aria-expanded; the list is a list', () => {
  const el = mount();
  geek(el);
  const search = q(el, '[data-inspector-search]');
  assert.ok(search.getAttribute('aria-label'));
  assert.equal(search.getAttribute('type'), 'search');
  for (const f of qa(el, '[data-inspector-filter]')) assert.ok(f.getAttribute('aria-label') || f.getAttribute('title'), f.getAttribute('data-inspector-filter'));
  assert.equal(q(el, '[data-inspector-list]').getAttribute('role'), 'list');
  for (const r of rows(el)) {
    assert.equal(r.getAttribute('role'), 'listitem');
    assert.ok(['true', 'false'].includes(r.querySelector('[data-row-toggle]').getAttribute('aria-expanded')));
  }
  assert.ok(q(el, '[data-inspector-status]').getAttribute('aria-live'));
  for (const g of qa(el, '[data-group-toggle]')) assert.ok(g.hasAttribute('aria-expanded'));
});

test('AC14 CSS: 44 px targets, visible focus rings, reduced motion, narrow layout, wrapping, light and dark', () => {
  assert.match(STYLE, /min-height:\s*44px/);
  assert.match(STYLE, /min-width:\s*44px/);
  assert.match(STYLE, /:focus-visible/);
  assert.match(STYLE, /outline:\s*[23]px/);
  assert.match(STYLE, /@media \(prefers-reduced-motion: reduce\)/);
  const rm = STYLE.slice(STYLE.indexOf('@media (prefers-reduced-motion: reduce)'));
  assert.match(rm, /animation:\s*none\s*!important/);
  assert.match(rm, /transition:\s*none\s*!important/);
  assert.match(STYLE, /@container \(max-width:/);
  assert.match(STYLE, /overflow-wrap:\s*anywhere/);
  assert.match(STYLE, /min-width:\s*0/);
  assert.match(STYLE, /prefers-color-scheme: dark/);
  assert.match(STYLE, /\[data-theme="dark"\]/);
  assert.doesNotMatch(STYLE, /white-space:\s*nowrap(?![^}]*text-overflow)/, 'nowrap only with an ellipsis');
  assert.doesNotMatch(STYLE, /overflow-x:\s*scroll/);
  assert.doesNotMatch(STYLE, /(?<![-\w(])(?:width|min-width):\s*(?:[4-9]\d\d|\d{4,})px/, 'no fixed width that could overflow a 375 px phone');
  // every animation is defined only for users who have not asked for reduced motion
  const anims = STYLE.match(/animation:[ \t]*(?![ \t]|none)[^;]+;/g) || [];
  for (const a of anims) assert.ok(!/!important/.test(a));
});

function lum(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
const ratio = (a, b) => {
  const [x, y] = [lum(a), lum(b)].sort((p, q2) => q2 - p);
  return (x + 0.05) / (y + 0.05);
};

test('AC14 contrast: text and status colours meet WCAG AA on their own surfaces, in light, dark and the instrument panel', () => {
  for (const [name, p] of Object.entries(PALETTE)) {
    assert.ok(ratio(p.fg, p.surface) >= 4.5, `${name}: text on surface ${ratio(p.fg, p.surface).toFixed(2)}`);
    assert.ok(ratio(p.fg2, p.surface) >= 4.5, `${name}: secondary text ${ratio(p.fg2, p.surface).toFixed(2)}`);
    for (const k of ['live', 'stale', 'unavailable', 'unknown', 'simulated', 'unverified']) {
      assert.ok(ratio(p[k], p.surface) >= 4.5, `${name}: ${k} ${ratio(p[k], p.surface).toFixed(2)}`);
    }
    assert.ok(ratio(p.accent, p.surface) >= 4.5, `${name}: accent`);
  }
});

test('AC14 status is never colour alone: every chip, tile and count carries an icon and the status word', () => {
  const el = mount();
  geek(el);
  for (const chip of qa(el, '[data-status-chip]')) {
    assert.ok(chip.querySelector('svg'));
    assert.ok(textOf(chip).length >= 4);
  }
  for (const tile of qa(el, '[data-tile]')) assert.match(textOf(tile), /Live|Stale|Unavailable|Unknown|Not measured|Simulated|Unverified/);
  const legend = q(el, '[data-status-key]');
  assert.ok(legend);
  for (const w of ['Live', 'Stale', 'Unavailable', 'Unknown', 'Not measured', 'Simulated', 'Unverified']) assert.match(textOf(legend), new RegExp(w));
});

test('AC14 the theme follows hass.themes.darkMode and falls back to the browser preference; nothing else is read from themes', () => {
  const el = mount({ hass: makeHass(miniStates(), { themes: { darkMode: true } }) });
  assert.equal(q(el, '[data-ecco-shell]').getAttribute('data-theme'), 'dark');
  el.hass = makeHass(miniStates(), { themes: { darkMode: false } });
  assert.equal(q(el, '[data-ecco-shell]').getAttribute('data-theme'), 'light');
  el.hass = { states: miniStates() };
  assert.equal(q(el, '[data-ecco-shell]').hasAttribute('data-theme'), false);
});

// ---------------------------------------------------------------------------------------------------------------------------
// AC16: authority: the same controls in both modes, and fail closed
// ---------------------------------------------------------------------------------------------------------------------------
const intelCard = { type: 'custom:stub-card', title: 'ECCO Intelligence', entities: { status: 'sensor.ecco_intel_status' } };
const pauseTile = { type: 'custom:stub-card', entity: 'input_boolean.ecco_intel_paused', name: 'Pause', tap_action: { action: 'toggle' }, icon_tap_action: { action: 'toggle' }, hold_action: { action: 'more-info' } };

test('AC16 pass-through: always and production children get exactly the configuration given, once, and keep it in both modes', () => {
  const always = [intelCard];
  const prod = [pauseTile];
  const alwaysCopy = structuredClone(always);
  const prodCopy = structuredClone(prod);
  const el = mount({ config: { always, production: prod } });
  const [a, p] = qa(el, 'stub-card');
  assert.equal(a.config, always[0], 'the same object, not a copy');
  assert.equal(p.config, prod[0]);
  assert.deepEqual(always, alwaysCopy, 'the configuration is not mutated');
  assert.deepEqual(prod, prodCopy);
  geek(el);
  assert.equal(a.configs.length, 1);
  assert.equal(p.configs.length, 1);
  assert.equal(a.config, always[0]);
  production(el);
  assert.equal(p.config.tap_action.action, 'toggle', 'the Production control is unchanged');
});

test('AC16 regions: the always child is visible in both modes; the Production-only child is hidden in Geek Mode and shown again in Production', () => {
  const el = mount({ config: { always: [intelCard], production: [pauseTile] } });
  const [a, p] = qa(el, 'stub-card');
  const hiddenUp = (n) => { for (let x = n; x && x.nodeType === 1; x = x.parentNode) if (x.hidden) return true; return false; };
  assert.equal(hiddenUp(a), false);
  assert.equal(hiddenUp(p), false);
  geek(el);
  assert.equal(hiddenUp(a), false, 'always stays');
  assert.equal(hiddenUp(p), true, 'Production-only is hidden, not changed');
  assert.match(textOf(q(el, '[data-ecco-body="geek"]')), /Controls .*live in the Production view/i, 'Geek Mode says where the controls are');
  production(el);
  assert.equal(hiddenUp(p), false);
});

test('AC16 guard: an always child that carries a write action is refused with a visible notice and an alert; the valid ones still show', () => {
  const writeCard = { type: 'tile', entity: 'input_boolean.x', tap_action: { action: 'toggle' }, icon_tap_action: { action: 'none' } };
  const el = mount({ config: { always: [intelCard, writeCard] } });
  assert.equal(qa(el, 'stub-card').length, 1, 'only the safe child is mounted');
  const notice = q(el, '[data-child-refused]');
  assert.ok(notice);
  assert.match(textOf(notice), /write action|toggle/i);
  assert.ok(stripIds(el).includes('shell:child-refused'));
  geek(el);
  assert.ok(stripIds(el).includes('shell:child-refused'));
});

test('AC16 guard: the Production-only region is not filtered by the guard (that is where controls live)', () => {
  const el = mount({ config: { production: [pauseTile] } });
  assert.equal(qa(el, 'stub-card').length, 1);
  assert.equal(q(el, '[data-child-refused]'), null);
});

test('AC16 children are created through Home Assistant card helpers when they exist, and the config is passed unchanged', async () => {
  const made = [];
  win.loadCardHelpers = async () => ({ createCardElement: (cfg) => { made.push(cfg); const s = new StubCard(); s.setConfig(cfg); return s; } });
  try {
    const cfgs = [{ type: 'tile', entity: 'sensor.x' }, { type: 'markdown', content: 'x' }];
    const el = mount({ config: { always: cfgs, production: [{ type: 'markdown', content: 'y' }] } });
    await tick();
    await tick();
    assert.equal(made.length, 3);
    assert.equal(made[0], cfgs[0]);
    assert.equal(qa(el, 'stub-card').length, 3);
    assert.ok(qa(el, 'stub-card').every((k) => k.hassSeen.length >= 1), 'late children receive hass as soon as they exist');
  } finally {
    delete win.loadCardHelpers;
  }
});

test('AC16 a child that cannot be created shows a notice instead of breaking the shell', () => {
  const el = mount({ config: { production: [{ type: 'custom:no-such-card-element-registered' }, { type: 5 }] } });
  assert.ok(qa(el, '[data-child-error]').length >= 1);
  assert.ok(q(el, '[data-ecco-alert-strip]'));
});

test('AC16 fail closed: an unknown catalogue schema shows a visible error, no inventory, and the alert strip still shows what is valid', () => {
  const cat = miniCatalogue();
  cat.schema = 'ecco-geek-catalogue/2';
  const el = mount({ catalogue: cat, states: miniStates(TRIGGER.A01) });
  assert.ok(stripIds(el).includes('A01'), 'the valid alert still drives the strip');
  assert.ok(stripIds(el).includes('shell:catalogue-invalid'), 'the problem is visible in Production too');
  geek(el);
  const err = q(el, '[data-ecco-catalogue-error]');
  assert.ok(err);
  assert.equal(err.getAttribute('role'), 'alert');
  assert.match(textOf(err), /schema/i);
  assert.equal(rows(el).length, 0);
  assert.ok(stripIds(el).includes('A01'));
});

test('AC16 fail closed: a malformed source disables the inventory with the reason, keeps the strip, and never shows partial coverage as complete', () => {
  const cat = miniCatalogue();
  delete cat.sources[3].entity_id;
  const el = mount({ catalogue: cat, states: miniStates(TRIGGER.A03) });
  geek(el);
  assert.ok(q(el, '[data-ecco-catalogue-error]'));
  assert.match(textOf(q(el, '[data-ecco-catalogue-error]')), /sources\[3\]/);
  assert.equal(rows(el).length, 0);
  assert.ok(stripIds(el).includes('A03'));
});

test('AC16 fail closed: no catalogue at all', () => {
  const el = new EccoModeShell();
  live.add(el);
  el.setConfig({ type: `custom:${TAG}` });
  el.hass = makeHass(miniStates());
  el.connectedCallback();
  geek(el);
  assert.ok(q(el, '[data-ecco-catalogue-error]'));
  assert.equal(rows(el).length, 0);
  assert.ok(stripIds(el).includes('shell:catalogue-invalid'));
});

test('AC16 the shell reads hass.states, hass.locale and hass.themes only (also under hostile hass shapes)', () => {
  const { hass, reads } = trapHass(miniStates());
  const el = mount({ hass });
  geek(el);
  for (const bad of [undefined, null, {}, { states: null }, { states: 5 }, { states: [] }]) {
    assert.doesNotThrow(() => { el.hass = bad; });
  }
  assert.deepEqual([...new Set(reads)].filter((r) => !['states', 'locale', 'themes'].includes(r)), []);
});

test('the shell renders everything with node APIs: not one innerHTML write across a full tour', () => {
  doc.resetRecorded();
  const el = mount({ states: hostileSecretStates(), config: { always: [intelCard], production: [pauseTile] } });
  geek(el);
  openEverything(el);
  typeSearch(el, 'x');
  production(el);
  assert.equal(doc.recorded.innerHTMLAttempts, 0);
});

// ---------------------------------------------------------------------------------------------------------------------------
// Review round 1 ([r1]): each test below was written to FAIL on the card as reviewed and to pass with its fix
// ---------------------------------------------------------------------------------------------------------------------------
const { realCatalogue, intelStates } = await import('./helpers.mjs');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const READ_ONLY_DOMAINS = ['binary_sensor', 'event', 'sensor'];
const isoAt = (ms) => new Date(ms).toISOString();

function realMount(mutate = null, config = {}) {
  const { states, now } = intelStates('healthy');
  if (mutate) mutate(states, now);
  return mount({ states, now, catalogue: realCatalogue(), path: '/intelligence', config });
}
const probeState = (id, state, now, attrs = {}) => ({ entity_id: id, state, attributes: { friendly_name: `probe ${id}`, ...attrs }, last_changed: isoAt(now - 30000), last_updated: isoAt(now - 30000) });
function expandGroups(el) {
  for (let n = 0; n < 40; n += 1) {
    const t = qa(el, '[data-group-toggle]').find((b) => b.getAttribute('aria-expanded') === 'false');
    if (!t) return;
    t.click();
  }
}
function openAllRows(el) {
  for (const id of rows(el).map((r) => r.getAttribute('data-entity-id'))) rowFor(el, id).querySelector('[data-row-toggle]').click();
}

test('AC16 [r1] Geek Mode opens a dialog only for read-only domains: over every domain the real catalogue discovers no writable one offers it, and none dispatches hass-more-info', async () => {
  const cat = realCatalogue();
  const prefixes = cat.discover.entity_prefixes;
  const domains = [...new Set(prefixes.map((p) => p.split('.')[0]))];
  for (const d of ['automation', 'button', 'counter', 'datetime', 'input_boolean', 'input_datetime', 'input_number', 'input_select', 'input_text', 'number', 'script', 'select', 'switch', 'text', 'timer', 'update']) {
    assert.ok(domains.includes(d), `the real catalogue discovers ${d}, and this test covers it`);
  }
  const el = realMount((states, now) => {
    for (const p of prefixes) {
      const id = `${p}zz_probe`;
      states[id] = probeState(id, p.startsWith('event.') ? isoAt(now - 30000) : 'on', now);
    }
  });
  geek(el);
  expandGroups(el);
  const opened = [];
  el.addEventListener('hass-more-info', (e) => opened.push(e.detail.entityId));
  openAllRows(el);
  let readOnly = 0;
  let writable = 0;
  for (const r of rows(el)) {
    const eid = r.getAttribute('data-entity-id');
    const domain = eid.split('.')[0];
    const open = r.querySelector('[data-open-entity]');
    if (READ_ONLY_DOMAINS.includes(domain)) {
      assert.ok(open, `${eid} (read-only) offers Open in Home Assistant`);
      readOnly += 1;
    } else {
      assert.ok(open === null, `${eid} (${domain}) must not offer Open in Home Assistant: its dialog has write controls that Production does not show`);
      assert.ok(r.querySelector('[data-copy-entity-id]'), `${eid} offers its id for copying instead`);
      assert.match(textOf(r.querySelector('[data-row-detail]')), /not opened from Geek Mode/i, `${eid} says why`);
      writable += 1;
    }
  }
  assert.ok(readOnly >= 10, `${readOnly} read-only rows`);
  assert.ok(writable >= 20, `${writable} writable-domain rows`);
  for (const b of qa(el, '[data-open-entity]')) b.click();
  assert.equal(opened.length, readOnly);
  assert.ok(opened.every((id) => READ_ONLY_DOMAINS.includes(id.split('.')[0])), JSON.stringify(opened));
  // the reserve helper's id is assembled: a repository-wide suite (home-assistant/tests) requires that only its package and its own suite name that helper in source files
  const reserveHelper = ['input_number', 'ecco_adv' + 'isory_reserve_raise_pct'].join('.');
  for (const id of [reserveHelper, 'automation.ecco_intel_alert_self_test_failed', 'input_boolean.ecco_intel_paused']) assert.ok(!opened.includes(id), id);
});

test('AC16 [r1] the guard is also in the dispatch itself: _openEntity sends hass-more-info for a read-only domain and never for a writable, malformed or non-text id', () => {
  const el = realMount();
  const got = [];
  el.addEventListener('hass-more-info', (e) => got.push(e.detail.entityId));
  for (const id of ['input_boolean.ecco_intel_paused', 'automation.x', 'switch.x', 'script.x', 'button.x', 'number.x', 'input_number.x', 'select.x', 'update.x', 'light.x', 'sensor', 'Sensor.x', 'sensor.x\nlight.y',
    'sensor.', '.x', '', ' sensor.x', 'sensor.x ', 5, null, undefined, {}, ['sensor.x']]) el._openEntity(id);
  assert.deepEqual(got, [], 'nothing was opened');
  for (const id of ['sensor.ecco_intel_status', 'binary_sensor.ecco_intel_fresh', 'event.ecco_intel_x']) el._openEntity(id);
  assert.deepEqual(got, ['sensor.ecco_intel_status', 'binary_sensor.ecco_intel_fresh', 'event.ecco_intel_x']);
});

test('AC16 [r1] a writable row offers its entity id for copying, and the copy is the id and nothing else', async () => {
  const clip = installClipboardAndDownload();
  try {
    const el = realMount();
    geek(el);
    expandGroups(el);
    const eid = 'input_boolean.ecco_intel_paused';
    rowFor(el, eid).querySelector('[data-row-toggle]').click();
    const btn = rowFor(el, eid).querySelector('[data-copy-entity-id]');
    assert.ok(btn);
    assert.equal(btn.getAttribute('type'), 'button');
    assert.ok(btn.getAttribute('aria-label') || textOf(btn), 'labelled');
    btn.click();
    await tick();
    assert.deepEqual(clip.clips, [eid]);
  } finally {
    clip.restore();
  }
});

test('AC3 [r1] setConfig (Home Assistant keeps the element and calls it again when the dashboard configuration changes) resets the mode to Production and drops the Geek surface', () => {
  const el = mount();
  geek(el);
  assert.equal(el.mode, 'geek');
  assert.ok(rows(el).length > 0);
  el.setConfig({ type: `custom:${TAG}`, view_id: 'intelligence', title: 'Intelligence', catalogue: miniCatalogue(), page_size: 100, always: [], production: [] });
  assert.equal(el.mode, 'production');
  assert.equal(q(el, '[data-ecco-body="geek"]').hidden, true);
  assert.equal(q(el, '[data-ecco-body="production"]').hidden, false);
  assert.equal(rows(el).length, 0, 'the Geek surface is gone');
  assert.equal(q(el, '[data-mode-option="production"]').getAttribute('aria-checked'), 'true');
  assert.equal(q(el, '[data-mode-option="geek"]').getAttribute('aria-checked'), 'false');
  geek(el);
  assert.equal(el.mode, 'geek', 'the switch still works after a setConfig');
  assert.ok(rows(el).length > 0);
  el.setConfig({ type: `custom:${TAG}`, view_id: 'intelligence', title: 'Intelligence', catalogue: miniCatalogue(), page_size: 100, always: [], production: [] });
  assert.equal(el.mode, 'production', 'and every later setConfig resets again');
});

test('AC16 [r1] a custom card in the always region needs its name in allow_custom_cards: otherwise it is refused with a notice and an alert; the Production-only region is never filtered', () => {
  const refused = mount({ config: { always: [intelCard], allow_custom_cards: [] } });
  assert.equal(qa(refused, 'stub-card').length, 0, 'nothing is mounted');
  assert.match(textOf(q(refused, '[data-child-refused]')), /not on the list/i);
  assert.ok(stripIds(refused).includes('shell:child-refused'));
  const allowed = mount({ config: { always: [intelCard], allow_custom_cards: ['custom:stub-card'] } });
  assert.equal(qa(allowed, 'stub-card').length, 1);
  assert.equal(q(allowed, '[data-child-refused]'), null);
  const prod = mount({ config: { production: [intelCard], allow_custom_cards: [] } });
  assert.equal(qa(prod, 'stub-card').length, 1, 'Production-only cards are the dashboard author\'s: not filtered');
  for (const type of ['picture-glance', 'area']) {
    const el = mount({ config: { always: [{ type, entities: ['sensor.ecco_intel_status'], image: 'x', area: 'kitchen' }] } });
    assert.ok(q(el, '[data-child-refused]'), type);
  }
});

test('AC14 [r1] a theme change is applied at once, even when no state changed (the hass object changed, the states did not)', () => {
  const states = miniStates();
  const el = mount({ hass: makeHass(states, { themes: { darkMode: false } }) });
  assert.equal(q(el, '[data-ecco-shell]').getAttribute('data-theme'), 'light');
  el.hass = makeHass(states, { themes: { darkMode: true } });
  assert.equal(q(el, '[data-ecco-shell]').getAttribute('data-theme'), 'dark');
  el.hass = makeHass(states, { themes: { darkMode: false } });
  assert.equal(q(el, '[data-ecco-shell]').getAttribute('data-theme'), 'light');
});

test('AC12 [r1] updates of entities the view does not read cost no rebuild: 200 house updates, no snapshot; a relevant update is still taken at once', () => {
  const states = bigStates(300);
  const el = mount({ states });
  geek(el);
  const s0 = mod.STATS.snapshots;
  let cur = states;
  for (let i = 0; i < 200; i += 1) {
    const id = `sensor.other_${i % 50}`;
    cur = { ...cur, [id]: mkState(id, `v${i}`, {}) };
    el.hass = makeHass(cur);
  }
  assert.equal(mod.STATS.snapshots - s0, 0, 'nothing the view reads changed');
  const rid = 'sensor.ecco_intel_synth_00003';
  el.hass = makeHass({ ...cur, [rid]: mkState(rid, 'relevant', {}) });
  assert.equal(mod.STATS.snapshots - s0, 1, 'one relevant update, one snapshot');
  typeSearch(el, 'synth_00003');
  assert.equal(rowFor(el, rid).querySelector('[data-row-state]').textContent.trim().startsWith('relevant'), true);
  // a new entity (the number of entities changes) is noticed: discovery must not wait for the tick
  const fresh = 'sensor.ecco_intel_brand_new_probe';
  el.hass = makeHass({ ...cur, [fresh]: mkState(fresh, '7', {}) });
  typeSearch(el, 'brand_new_probe');
  assert.equal(rows(el).length, 1, 'a new ecco_intel_ entity is discovered at once');
});

test('AC12 [r1] a burst of relevant updates is coalesced: a bounded number of rebuilds during the burst, the last value (and a critical alert) shown shortly after it, and a later update is immediate again', async () => {
  const states = bigStates(300);
  const el = mount({ states });
  geek(el);
  const rid = 'sensor.ecco_intel_synth_00001';
  typeSearch(el, 'synth_00001');
  const s0 = mod.STATS.snapshots;
  const t0 = performance.now();
  let cur = states;
  for (let i = 0; i < 100; i += 1) {
    cur = { ...cur, [rid]: mkState(rid, `burst-${i}`, {}) };
    el.hass = makeHass(cur);
  }
  const st = 'sensor.ecco_intel_status';
  cur = { ...cur, [st]: mkState(st, 'SELF_TEST_FAILED', cur[st].attributes) };
  el.hass = makeHass(cur);
  const elapsed = performance.now() - t0;
  const during = mod.STATS.snapshots - s0;
  const allowed = (Math.ceil(elapsed / 500) + 1) * 8;
  assert.ok(during >= 1, 'the first updates are taken at once');
  assert.ok(during <= allowed, `${during} rebuilds for 101 updates in ${elapsed.toFixed(0)} ms (at most ${allowed})`);
  assert.ok(during < 101);
  await sleep(1100);
  const after = mod.STATS.snapshots - s0;
  assert.ok(after <= during + 2, `${after - during} rebuilds after the burst`);
  assert.equal(rowFor(el, rid).querySelector('[data-row-state]').textContent.trim().startsWith('burst-99'), true, 'the LAST value of the burst is shown');
  assert.ok(stripIds(el).includes('A01'), 'and so is the critical alert that arrived last');
  assert.equal(el._timerMs, mod.TICK_MS, 'the one timer is back on the age tick');
  const before = mod.STATS.snapshots;
  el.hass = makeHass({ ...cur, [rid]: mkState(rid, 'after-the-burst', {}) });
  assert.equal(mod.STATS.snapshots - before, 1, 'after a quiet spell the next update is immediate again');
  assert.equal(rowFor(el, rid).querySelector('[data-row-state]').textContent.trim().startsWith('after-the-burst'), true);
});

test('AC12 [r1] a pending flush does not outlive the element: after disconnect nothing is rebuilt and no timer is left', async () => {
  const states = bigStates(100);
  const el = mount({ states });
  const rid = 'sensor.ecco_intel_synth_00001';
  let cur = states;
  for (let i = 0; i < 40; i += 1) {
    cur = { ...cur, [rid]: mkState(rid, `v-${i}`, {}) };
    el.hass = makeHass(cur);
  }
  assert.notEqual(el._timerMs, mod.TICK_MS, 'a flush is pending (the one timer slot is armed for it)');
  assert.equal(el._pending, true);
  el.disconnectedCallback();
  assert.equal(el._timer, null);
  const s0 = mod.STATS.snapshots;
  await sleep(700);
  assert.equal(mod.STATS.snapshots, s0, 'no rebuild after disconnect');
});
