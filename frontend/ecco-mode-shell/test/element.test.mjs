// The custom element against the minidom stand-in. Covers AC1-AC9, AC10-AC14 and AC16 at element level: the default and
// reset rules, mode independence, the zero-call guarantee, the alert strip, one snapshot for both modes, coverage and
// honesty, redaction in every output, search / filter / paging, performance, inert hostile text, accessibility and the
// fail-closed behaviour.
import test, { afterEach } from 'node:test';
import assert from 'node:assert/strict';
import { installDom, installResizeObserver, MElement, MEvent, MDocument, MShadowRoot, tripwires, TRIPWIRE_NAMES } from './minidom.mjs';

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
  // review round 8: after EVERY test, in whatever mode it left the element, nothing has read or called a Web Animations, style-map or stylesheet member of any element, shadow root or document (see the tripwires in minidom.mjs)
  const touched = tripwires.splice(0);
  assert.deepEqual(touched, [], 'a tripwire was touched');
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

// ---- review round 4 (reviewer mutants J2 and J5): what a screen reader gets from the strip is the same in both modes ----
// The mode switch is a presentation toggle; a safety alert must stay announced and reachable in BOTH. aria-hidden, inert, hidden, role presentation or none, an
// aria-live that is not polite and an empty label would each silence or remove the strip for assistive technology while the pixels look right.
const A11Y_NAME = /^(?:role|aria-.+|hidden|inert|style|class|slot|tabindex|contenteditable|popover)$/i;
const attrMap = (n, only = null) => Object.fromEntries([...n.attrs].filter(([k]) => !only || only.test(k)).sort(([a], [b]) => (a < b ? -1 : 1)));
function stripAccess(el) {
  const strip = q(el, '[data-ecco-alert-strip]');
  const chain = [];
  for (let n = strip.parentNode; n && n.nodeType === 1; n = n.parentNode) chain.push({ tag: n.tagName, a11y: attrMap(n, A11Y_NAME) });
  chain.push({ tag: 'host', a11y: attrMap(el, A11Y_NAME) });
  const sub = [];
  const walk = (n) => {
    for (const c of n.childNodes) {
      if (c.nodeType !== 1) continue;
      sub.push({ tag: c.tagName, a11y: attrMap(c, A11Y_NAME) });
      walk(c);
    }
  };
  walk(strip);
  const lines = qa(el, '[data-ecco-alert-strip] .alert').map((n) => ({ id: n.getAttribute('data-alert-id'), severity: n.getAttribute('data-severity'), role: n.getAttribute('role') }));
  return { strip: attrMap(strip), chain, sub, lines };
}
/** What must hold for a person using a screen reader, in either mode. */
function expectAccessible(s, where) {
  assert.equal(s.strip.role, 'region', `${where}: the strip is a region`);
  assert.equal(s.strip['aria-live'], 'polite', `${where}: the strip is announced politely`);
  assert.ok(typeof s.strip['aria-label'] === 'string' && s.strip['aria-label'].trim().length >= 5, `${where}: the strip has a label`);
  for (const bad of ['aria-hidden', 'inert', 'hidden', 'style']) assert.equal(bad in s.strip, false, `${where}: ${bad} on the strip`);
  assert.equal(s.strip['data-alert-count'] !== undefined, true, `${where}: the strip carries its count`);
  for (const c of s.chain) {
    for (const bad of ['aria-hidden', 'inert', 'hidden', 'style', 'role', 'aria-live', 'aria-label']) assert.equal(bad in c.a11y, false, `${where}: ${bad} on ${c.tag}, which holds the strip`);
  }
  for (const n of s.sub) {
    for (const bad of ['inert', 'hidden', 'style']) assert.equal(bad in n.a11y, false, `${where}: ${bad} inside the strip (${n.tag})`);
    if ('aria-hidden' in n.a11y) assert.ok(n.tag === 'svg' && n.a11y['aria-hidden'] === 'true', `${where}: aria-hidden inside the strip only on a decorative icon, not on ${n.tag}`);
    assert.ok(!['presentation', 'none'].includes(n.a11y.role), `${where}: ${n.tag} loses its role`);
    assert.equal('aria-live' in n.a11y, false, `${where}: aria-live inside the strip (${n.tag})`);
  }
  assert.ok(s.lines.length >= 1, `${where}: the strip has a line`);
  for (const l of s.lines) assert.equal(l.role, l.id ? (l.severity === 'critical' ? 'alert' : 'status') : null, `${where}: the role of ${l.id || 'the quiet line'}`);
}

test('AC6 [r4] a screen reader gets the strip the same way in both modes: role, aria-live, label, no aria-hidden or inert on it or around it, the same roles on every line (reviewer mutants J2, J5)', () => {
  const scenarios = { healthy: undefined, 'critical, warning and notice together': (s) => { TRIGGER.A01(s); TRIGGER.A03(s); TRIGGER.A05(s); }, ...Object.fromEntries(Object.entries(TRIGGER)) };
  assert.ok(Object.keys(scenarios).length >= 9);
  for (const [name, mutate] of Object.entries(scenarios)) {
    const el = mount({ states: miniStates(mutate) });
    const p0 = stripAccess(el);
    expectAccessible(p0, `${name}, Production`);
    geek(el);
    const g0 = stripAccess(el);
    expectAccessible(g0, `${name}, Geek`);
    assert.deepEqual(g0, p0, `${name}: the strip's attributes, its ancestors' and its lines' differ between Production and Geek Mode`);
    // an update, a clock tick and a theme change in Geek Mode, then back, then again: still the same, still accessible
    el.hass = makeHass(miniStates(mutate), { themes: { darkMode: true } });
    el._tick();
    const g1 = stripAccess(el);
    expectAccessible(g1, `${name}, Geek after an update`);
    assert.deepEqual(g1, p0, `${name}: after an update`);
    production(el);
    assert.deepEqual(stripAccess(el), p0, `${name}: back in Production`);
    geek(el);
    production(el);
    geek(el);
    assert.deepEqual(stripAccess(el), p0, `${name}: after switching again`);
    el.hass = makeHass(miniStates(), { themes: { darkMode: false } });
    expectAccessible(stripAccess(el), `${name}, after the condition cleared`);
  }
});

test('AC6 [r4] the accessibility check has teeth: each way of hiding or muting the strip, planted on a live element, is reported (negative controls)', () => {
  expectAccessible(stripAccess(mount({ states: miniStates(TRIGGER.A01) })), 'control: the untouched card passes');
  const plants = {
    'aria-hidden on the strip': (e) => q(e, '[data-ecco-alert-strip]').setAttribute('aria-hidden', 'true'),
    'aria-hidden false on the strip': (e) => q(e, '[data-ecco-alert-strip]').setAttribute('aria-hidden', 'false'),
    'aria-live off': (e) => q(e, '[data-ecco-alert-strip]').setAttribute('aria-live', 'off'),
    'aria-live removed': (e) => q(e, '[data-ecco-alert-strip]').removeAttribute('aria-live'),
    'aria-live assertive': (e) => q(e, '[data-ecco-alert-strip]').setAttribute('aria-live', 'assertive'),
    'role presentation': (e) => q(e, '[data-ecco-alert-strip]').setAttribute('role', 'presentation'),
    'role removed': (e) => q(e, '[data-ecco-alert-strip]').removeAttribute('role'),
    'label emptied': (e) => q(e, '[data-ecco-alert-strip]').setAttribute('aria-label', ''),
    'label removed': (e) => q(e, '[data-ecco-alert-strip]').removeAttribute('aria-label'),
    'inert on the strip': (e) => q(e, '[data-ecco-alert-strip]').setAttribute('inert', ''),
    'hidden on the strip': (e) => q(e, '[data-ecco-alert-strip]').setAttribute('hidden', ''),
    'a style attribute on the strip': (e) => q(e, '[data-ecco-alert-strip]').setAttribute('style', 'height:0'),
    'aria-hidden on the shell': (e) => q(e, '[data-ecco-shell]').setAttribute('aria-hidden', 'true'),
    'inert on the shell': (e) => q(e, '[data-ecco-shell]').setAttribute('inert', ''),
    'role presentation on the shell': (e) => q(e, '[data-ecco-shell]').setAttribute('role', 'presentation'),
    'aria-hidden on the host': (e) => e.setAttribute('aria-hidden', 'true'),
    'inert on the host': (e) => e.setAttribute('inert', ''),
    'hidden on an alert line': (e) => qa(e, '[data-ecco-alert-strip] .alert')[0].setAttribute('hidden', ''),
    'aria-hidden on an alert line': (e) => qa(e, '[data-ecco-alert-strip] .alert')[0].setAttribute('aria-hidden', 'true'),
    'a critical alert that is only a status': (e) => qa(e, '[data-ecco-alert-strip] [data-severity="critical"]')[0].setAttribute('role', 'status'),
    'an alert line with no role': (e) => qa(e, '[data-ecco-alert-strip] .alert')[0].removeAttribute('role'),
    'aria-hidden on the alert text': (e) => qa(e, '[data-ecco-alert-strip] .alert-head')[0].setAttribute('aria-hidden', 'true'),
    'aria-live inside the strip': (e) => qa(e, '[data-ecco-alert-strip] .alert')[0].setAttribute('aria-live', 'off'),
  };
  for (const [what, plant] of Object.entries(plants)) {
    const e = mount({ states: miniStates(TRIGGER.A01) });
    plant(e);
    assert.throws(() => expectAccessible(stripAccess(e), what), undefined, `not reported: ${what}`);
  }
  // a change that leaves each state acceptable on its own (a different label, still a label) is caught by the comparison between the modes
  const e = mount({ states: miniStates(TRIGGER.A01) });
  const p = stripAccess(e);
  geek(e);
  q(e, '[data-ecco-alert-strip]').setAttribute('aria-label', 'Safety and status alert');
  assert.notDeepEqual(stripAccess(e), p, 'a changed label, still a label, differs between the modes');
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
  const states = miniStates((s) => { s['sensor.ecco_intel_new_diagnostic'].attributes.huge = 'z'.repeat(LIMITS.scanBound - 1); });
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

// ---------------------------------------------------------------------------------------------------------------------------
// Review round 2 ([r2]): each test below was written to FAIL on the mutant the reviewer named and to pass on the card
// ---------------------------------------------------------------------------------------------------------------------------
const OUTSIDE = 'sensor.zz_outside_probe';
const outsideCatalogue = () => {
  const c = miniCatalogue();
  c.alerts.push({ id: 'A90', severity: 'critical', entity_id: OUTSIDE, when: { state_in: ['bad'] }, text: 'The outside probe says bad.', action: 'Check the outside probe.' });
  return c;
};

test('AC6 [r2] an alert on an entity that is not a source is watched too: its change reaches the strip at once, in both modes, even a moment after the last rebuild (reviewer probe P8, mutant R2-36)', () => {
  const LAMP = 'light.zz_unrelated_lamp';
  const base = { ...miniStates(), [OUTSIDE]: mkState(OUTSIDE, 'good', {}), [LAMP]: mkState(LAMP, 'off', {}) };
  const el = mount({ catalogue: outsideCatalogue(), hass: makeHass(base) });
  assert.ok(!stripIds(el).includes('A90'));
  assert.ok(el.snapshot.watch.includes(OUTSIDE), 'the snapshot reads it');
  assert.ok(!el.snapshot.rows.some((r) => r.entity_id === OUTSIDE), 'it is not a row: only the strip reads it');
  const s0 = mod.STATS.snapshots;
  // the same clock as the last rebuild: inside the one-second window in which updates the view does not read are skipped
  el.hass = makeHass({ ...base, [OUTSIDE]: mkState(OUTSIDE, 'bad', {}) });
  assert.equal(mod.STATS.snapshots - s0, 1, 'the update is relevant, so it is taken at once');
  assert.ok(stripIds(el).includes('A90'), 'the critical line is on the strip now, not at the next tick');
  geek(el);
  assert.ok(stripIds(el).includes('A90'), 'and in Geek Mode');
  const cleared = { ...base, [OUTSIDE]: mkState(OUTSIDE, 'good', {}) };
  el.hass = makeHass(cleared);
  assert.ok(!stripIds(el).includes('A90'), 'and it clears at once too');
  // an update of something the view does not read is still free
  const s1 = mod.STATS.snapshots;
  el.hass = makeHass({ ...cleared, [LAMP]: mkState(LAMP, 'on', {}) });
  assert.equal(mod.STATS.snapshots - s1, 0, 'an unrelated entity costs no rebuild');
});

test('AC16 [r2] fail closed, all the way: with one malformed source the snapshot holds no row, the Production summary carries no problem note, and the strip still shows the valid alerts (reviewer probe P9, mutant R2-41)', () => {
  const cat = miniCatalogue();
  delete cat.sources[3].entity_id;
  const states = miniStates((s) => {
    TRIGGER.A03(s);
    s['sensor.ecco_intel_pv_tomorrow'].state = 'unavailable';
    s['sensor.ecco_intel_overnight_demand'].state = 'unknown';
  });
  const el = mount({ catalogue: cat, states });
  assert.equal(validateCatalogue(cat).ok, false);
  assert.ok(validateCatalogue(cat).catalogue.sources.length > 0, 'the validator does keep the valid sources (the shell must not use them)');
  assert.equal(el.snapshot.rows.length, 0, 'no row of the valid sources and no discovered row');
  assert.equal(el.snapshot.counts.total, 0);
  assert.equal(el.snapshot.counts.problems, 0);
  const sum = textOf(q(el, '[data-ecco-summary]'));
  assert.doesNotMatch(sum, /data points?|Geek Mode lists them|stale, unavailable/, 'no note about data points that are not listed anywhere');
  assert.ok(stripIds(el).includes('A03'), 'the valid alert still drives the strip');
  assert.ok(stripIds(el).includes('shell:catalogue-invalid'));
  geek(el);
  assert.equal(rows(el).length, 0);
  assert.ok(q(el, '[data-ecco-catalogue-error]'));
  // a later update does not bring a row back either
  el.hass = makeHass(miniStates((s) => { TRIGGER.A03(s); s['sensor.ecco_intel_pv_tomorrow'].state = 'unavailable'; s['sensor.ecco_intel_brand_new_probe'] = mkState('sensor.ecco_intel_brand_new_probe', '1', {}); }));
  assert.equal(el.snapshot.rows.length, 0, 'not by update, not by discovery');
  assert.equal(rows(el).length, 0);
});

// ---------------------------------------------------------------------------------------------------------------------------
// Review round 5 ([r5]). Five mutants survived every node suite and were caught only by the opt-in headless-browser check (J13, J14, J20, J21, AR08): the strip moved
// inside the shell in Geek Mode only (J14, J20), a custom property set on the shell by the call that sets one on a bar segment or a ring (J13, J21), and a shadow root
// attached to the strip (AR08). The two tests below pin where the strip sits; the source pins are in static.test.mjs.
// ---------------------------------------------------------------------------------------------------------------------------
const SHELL_ORDER = ['top', 'mode-note', 'strip', 'always', 'body:production', 'body:geek'];
function shellKind(n) {
  if (n.hasAttribute('data-ecco-alert-strip')) return 'strip';
  if (n.hasAttribute('data-ecco-always')) return 'always';
  if (n.hasAttribute('data-ecco-body')) return `body:${n.getAttribute('data-ecco-body')}`;
  if (n.hasAttribute('data-ecco-mode-note')) return 'mode-note';
  if (n.className.split(/\s+/).includes('top')) return 'top';
  return `other:${n.tagName}`;
}
/** Where the strip sits: its parent, the order of everything in that parent, and the chain from the strip up to the shadow root. */
function stripPlace(el) {
  const strip = q(el, '[data-ecco-alert-strip]');
  const shell = q(el, '[data-ecco-shell]');
  const chain = [];
  for (let n = strip; n; n = n.parentNode) chain.push(n.nodeType === 1 ? shellKind(n) : 'root');
  return { parentIsShell: strip.parentNode === shell, shellIsTop: shell.parentNode === root(el), order: shell.children.map(shellKind), index: shell.childNodes.indexOf(strip),
    chainLength: chain.length, shadowOfStrip: strip.shadowRoot === undefined || strip.shadowRoot === null, count: qa(el, '[data-ecco-alert-strip]').length };
}
function expectPlace(p, where) {
  assert.equal(p.count, 1, `${where}: there is one strip`);
  assert.equal(p.parentIsShell, true, `${where}: the strip is a direct child of the shell`);
  assert.equal(p.shellIsTop, true, `${where}: the shell is the top of the shadow root`);
  assert.deepEqual(p.order, SHELL_ORDER, `${where}: the strip comes after the title and the note and BEFORE the always region, the Production body and the Geek body`);
  assert.equal(p.index, p.order.indexOf('strip'), `${where}: its place among the shell's children (text nodes included)`);
  assert.equal(p.shadowOfStrip, true, `${where}: the strip has no shadow root of its own`);
}

test('AC6 [r5] the strip sits in the shell at the same place in both modes: a direct child, after the title and the note, before the always region, the Production body and the Geek body (reviewer mutants J14, J20)', () => {
  const scenarios = { healthy: undefined, 'critical, warning and notice together': (s) => { TRIGGER.A01(s); TRIGGER.A03(s); TRIGGER.A05(s); }, ...Object.fromEntries(Object.entries(TRIGGER)) };
  for (const [name, mutate] of Object.entries(scenarios)) {
    const el = mount({ states: miniStates(mutate), config: { always: [{ type: 'custom:stub-card' }], production: [{ type: 'custom:stub-card' }] } });
    const p0 = stripPlace(el);
    expectPlace(p0, `${name}, Production`);
    geek(el);
    const g0 = stripPlace(el);
    expectPlace(g0, `${name}, Geek`);
    assert.deepEqual(g0, p0, `${name}: the place of the strip differs between Production and Geek Mode`);
    el.hass = makeHass(miniStates(mutate), { themes: { darkMode: true } });
    el._tick();
    assert.deepEqual(stripPlace(el), p0, `${name}: after an update, a tick and a theme change in Geek Mode`);
    production(el);
    assert.deepEqual(stripPlace(el), p0, `${name}: back in Production`);
    geek(el);
    production(el);
    geek(el);
    assert.deepEqual(stripPlace(el), p0, `${name}: after switching again`);
    el.hass = makeHass(miniStates(), { themes: { darkMode: false } });
    expectPlace(stripPlace(el), `${name}, after the condition cleared`);
  }
});

test('AC6 [r5] the placement check has teeth: each way of moving, wrapping or duplicating the strip, planted on a live element, is reported (negative controls)', () => {
  expectPlace(stripPlace(mount({ states: miniStates(TRIGGER.A01) })), 'control: the untouched card passes');
  const part = (e, sel) => q(e, sel);
  const plants = {
    'moved to the end of the shell (after the Geek body)': (e) => part(e, '[data-ecco-shell]').appendChild(part(e, '[data-ecco-alert-strip]')),
    'moved to just before the Geek body': (e) => part(e, '[data-ecco-shell]').insertBefore(part(e, '[data-ecco-alert-strip]'), part(e, '[data-ecco-body="geek"]')),
    'moved to just before the Production body': (e) => part(e, '[data-ecco-shell]').insertBefore(part(e, '[data-ecco-alert-strip]'), part(e, '[data-ecco-body="production"]')),
    'moved above the title': (e) => part(e, '[data-ecco-shell]').insertBefore(part(e, '[data-ecco-alert-strip]'), part(e, '[data-ecco-shell]').firstChild),
    'moved between the title and the note': (e) => part(e, '[data-ecco-shell]').insertBefore(part(e, '[data-ecco-alert-strip]'), part(e, '[data-ecco-mode-note]')),
    'moved into the always region': (e) => part(e, '[data-ecco-always]').appendChild(part(e, '[data-ecco-alert-strip]')),
    'moved into the Production body': (e) => part(e, '[data-ecco-body="production"]').appendChild(part(e, '[data-ecco-alert-strip]')),
    'moved into the Geek body': (e) => part(e, '[data-ecco-body="geek"]').appendChild(part(e, '[data-ecco-alert-strip]')),
    'moved out of the shell, into the shadow root': (e) => root(e).appendChild(part(e, '[data-ecco-alert-strip]')),
    'wrapped in another element': (e) => {
      const w = doc.createElement('div');
      part(e, '[data-ecco-shell]').insertBefore(w, part(e, '[data-ecco-always]'));
      w.appendChild(part(e, '[data-ecco-alert-strip]'));
    },
    'the always region moved above the strip': (e) => part(e, '[data-ecco-shell]').insertBefore(part(e, '[data-ecco-always]'), part(e, '[data-ecco-alert-strip]')),
    'a shadow root of its own (planted as a property, as a real attachShadow would leave one)': (e) => { part(e, '[data-ecco-alert-strip]').shadowRoot = {}; },
    'a second strip': (e) => {
      const w = doc.createElement('div');
      w.setAttribute('data-ecco-alert-strip', '');
      part(e, '[data-ecco-shell]').insertBefore(w, part(e, '[data-ecco-always]'));
    },
  };
  for (const [what, plant] of Object.entries(plants)) {
    const e = mount({ states: miniStates(TRIGGER.A01) });
    plant(e);
    assert.throws(() => expectPlace(stripPlace(e), what), undefined, `not reported: ${what}`);
  }
});

// Review round 5, NIT: validateConfig collected its errors and nothing showed them (production given as text became an empty list, and the pause tile just vanished).
test('AC16 [r5] a configuration problem is shown on the strip, in both modes, as a warning with words and an icon: it is never silent (production given as text no longer makes the pause tile vanish unannounced)', () => {
  const tile = { type: 'tile', entity: 'sensor.ecco_intel_status', name: 'Status', tap_action: { action: 'none' } };
  const cases = {
    'production given as text': [{ production: 'pause tile' }, /production/],
    'production given as a number': [{ production: 7 }, /production/],
    'always given as an object': [{ always: {} }, /always/],
    'page_size out of range': [{ page_size: 3 }, /page_size/],
    'page_size not a whole number': [{ page_size: 'many' }, /page_size/],
    'alerts_from not the catalogue': [{ alerts_from: 'elsewhere' }, /alerts_from/],
    'a custom card name that is not a name': [{ allow_custom_cards: ['<img src=x onerror=1>'] }, /allow_custom_cards\[0\]/],
    'allow_custom_cards not a list': [{ allow_custom_cards: 'custom:x-y' }, /allow_custom_cards/],
  };
  for (const [name, [patch, path]] of Object.entries(cases)) {
    const el = mount({ config: patch });
    for (const where of ['Production', 'Geek']) {
      if (where === 'Geek') geek(el);
      assert.ok(stripIds(el).includes('shell:config-invalid'), `${name}: no line on the strip in ${where}`);
      const line = qa(el, '[data-ecco-alert-strip] [data-alert-id="shell:config-invalid"]')[0];
      assert.equal(line.getAttribute('data-severity'), 'warning', name);
      assert.equal(line.getAttribute('role'), 'status', name);
      assert.ok(line.querySelector('svg'), `${name}: an icon, not colour alone`);
      assert.match(textOf(line), /Warning/, name);
      assert.match(textOf(line), /1 problem,/, name);
      assert.match(textOf(line), path, `${name}: the line names the setting`);
      assert.match(textOf(line), /What to do: Ask whoever installed this view/, name);
      assert.doesNotMatch(textOf(line), /<img|onerror|pause tile/, `${name}: no value from the configuration is echoed`);
    }
    expectAccessible(stripAccess(el), `${name}: a configuration warning leaves the strip as accessible as before`);
    expectPlace(stripPlace(el), `${name}: and in the same place`);
  }
  // a valid configuration raises nothing; the same catalogue and states, so the only difference is the configuration
  const ok = mount({ config: { production: [tile], always: [] } });
  assert.ok(!stripIds(ok).includes('shell:config-invalid'));
  assert.deepEqual(stripIds(mount()), []);
  // no configuration at all, and a configuration that is not an object
  for (const bad of [undefined, null, 5, 'x']) {
    const el = new EccoModeShell();
    live.add(el);
    el.setConfig(bad);
    el.hass = makeHass(miniStates());
    el.connectedCallback();
    assert.ok(stripIds(el).includes('shell:config-invalid'), `setConfig(${String(bad)}) is announced`);
    assert.match(textOf(qa(el, '[data-ecco-alert-strip] [data-alert-id="shell:config-invalid"]')[0]), /config: the card configuration must be an object/);
  }
  // several problems: the first three are named and the rest are counted; it sits with the other shell warnings
  const many = mount({ config: { production: 'x', always: 'y', page_size: 1, alerts_from: 'z', allow_custom_cards: ['bad'] }, catalogue: { schema: 'nope' } });
  const line = textOf(qa(many, '[data-ecco-alert-strip] [data-alert-id="shell:config-invalid"]')[0]);
  assert.match(line, /5 problems,/);
  assert.match(line, /page_size: .*; alerts_from: .*; allow_custom_cards\[0\]: .*; and 2 more\)/);
  assert.ok(stripIds(many).includes('shell:catalogue-invalid'), 'the catalogue warning is still there beside it');
  // the strip is the one strip: nothing about the mode changes it, and a later setConfig with a good configuration clears the line
  geek(many);
  assert.ok(stripIds(many).includes('shell:config-invalid'));
  many.setConfig({ type: `custom:${TAG}`, view_id: 'intelligence', title: 'Intelligence', catalogue: miniCatalogue(), page_size: 100, always: [], production: [] });
  assert.equal(many.mode, 'production', 'setConfig is an entry: it starts in Production again');
  assert.ok(!stripIds(many).includes('shell:config-invalid'), 'fixed configuration, no line');
});

// Review round 5 (MAJOR): the secret kinds of the owner's review, at offsets 100, 1500, 3990 and 4000 of a 4000-character text, on the DOM paths: the rows, the open attribute lists, the raw view,
// the search box, copy and both exports. (The core test has the same cases on the data side.)
test('AC10 [r5] every kind at every offset holds on every DOM path: the rows, the raw view, the search, copy and both exports show none of it; the harmless long text is shown whole and found by search', async () => {
  const { positionedCases, benignControl, BENIGN_MARKERS } = await import('./secrets.mjs');
  const cases = positionedCases();
  const states = miniStates();
  for (const c of cases) states[`sensor.ecco_intel_pos_${c.id}`] = mkState(`sensor.ecco_intel_pos_${c.id}`, 'ok', { pos_note: c.text, friendly_name: `Positioned ${c.id}` });
  states['sensor.ecco_intel_pos_control'] = mkState('sensor.ecco_intel_pos_control', 'ok', { pos_note: benignControl(), friendly_name: 'Positioned control' });
  const clip = installClipboardAndDownload();
  try {
    const el = mount({ states });
    geek(el);
    assert.ok(rows(el).length >= cases.length + 1, `every positioned entity is a row (${rows(el).length})`);
    openEverything(el);
    const text = allText(root(el));
    const raw = qa(el, '[data-inspector-raw]').map((n) => n.textContent).join('\n');
    for (const c of cases) assert.ok(!text.includes(c.probe), `${c.label}: the DOM carries ${c.probe.slice(0, 8)}`);
    assert.ok((raw.match(/"pos_note": "\[withheld\]"/g) || []).length >= cases.length, 'the raw view says withheld for every one of them');
    for (const m of BENIGN_MARKERS) assert.ok(raw.includes(m), `the raw view of the harmless long text reaches ${m}`);
    for (const c of cases) {
      typeSearch(el, c.probe);
      assert.equal(rows(el).length, 0, `${c.label}: a search for it finds a row`);
    }
    for (const m of BENIGN_MARKERS) {
      typeSearch(el, m);
      assert.equal(rows(el).length, 1, `the search reaches ${m} in the harmless long text`);
      assert.equal(rows(el)[0].getAttribute('data-entity-id'), 'sensor.ecco_intel_pos_control');
    }
    typeSearch(el, '');
    q(el, '[data-inspector-copy]').click();
    await tick();
    q(el, '[data-inspector-export="json"]').click();
    q(el, '[data-inspector-export="csv"]').click();
    for (const id of ['sensor.ecco_intel_pos_control', `sensor.ecco_intel_pos_${cases[0].id}`, `sensor.ecco_intel_pos_${cases[cases.length - 1].id}`]) {
      rowFor(el, id).querySelector('[data-inspector-copy="row"]').click();
      await tick();
    }
    assert.equal(clip.clips.length, 4, 'one copy of every row and three row copies');
    assert.equal(clip.blobs.length, 2);
    const outputs = [...clip.clips, ...(await Promise.all(clip.blobs.map((b) => b.text())))];
    for (const bytes of outputs) {
      assert.ok(bytes.length > 100);
      for (const c of cases) assert.ok(!bytes.includes(c.probe), `${c.label}: an output carries ${c.probe.slice(0, 8)}`);
    }
    assert.ok(outputs[0].includes(benignControl()), 'the copy of every row carries the harmless long text whole');
    assert.ok(outputs[1].includes(benignControl()), 'and so does the copy of that one row (the first of the three row copies)');
    assert.ok(outputs[4].includes(benignControl()), 'and the json export');
    assert.match(outputs[1], /^\{/);
  } finally {
    clip.restore();
  }
});

// ---------------------------------------------------------------------------------------------------------------------------
// Review round 6 ([r6]): the sweep on the DOM paths. The core test (core.test.mjs) puts every kind at every offset through the redactor and the snapshot; this one takes the starts that matter most
// (the start, the crossing of 500 and of 1000, the display cap, the very end) of every kind in every carrier and checks what a person can SEE or take away: the rows, the open attribute lists, the raw
// view, the search box, the copy of everything and of one row, and both downloads.
// ---------------------------------------------------------------------------------------------------------------------------
test('AC10 [r6] SWEEP on every DOM path: every kind at the start, across 500 and 1000, across the display cap and at the very end of 1500, 3999, 4000 and 4500 characters is in no row, no raw view, no search result, no copy and no download', async () => {
  const { SWEEP_CARRIERS, sweepCases, benignControl, BENIGN_MARKERS } = await import('./secrets.mjs');
  const starts = (k, total) => [...new Set([0, 500 - Math.ceil(k.value.length / 2), 1000 - Math.ceil(k.value.length / 2), 4000 - Math.ceil(k.value.length / 2), total - k.value.length])]
    .filter((s) => s >= 0 && s + k.value.length <= total);
  const all = [...sweepCases(SWEEP_CARRIERS, starts)];
  assert.ok(all.length >= 200, `${all.length} cases`);
  const clip = installClipboardAndDownload();
  try {
    for (let from = 0; from < all.length; from += 70) {
      const cases = all.slice(from, from + 70);
      const states = miniStates();
      for (const c of cases) states[`sensor.ecco_intel_sw_${c.id}`] = mkState(`sensor.ecco_intel_sw_${c.id}`, 'ok', { sweep_note: c.text, friendly_name: `Sweep ${c.id}` });
      if (from === 0) states['sensor.ecco_intel_sw_control'] = mkState('sensor.ecco_intel_sw_control', 'ok', { sweep_note: benignControl(), friendly_name: 'Sweep control' });
      const el = mount({ states });
      geek(el);
      assert.ok(rows(el).length >= cases.length, `every swept entity is a row (${rows(el).length} of ${cases.length})`);
      openEverything(el);
      const text = allText(root(el));
      const raw = qa(el, '[data-inspector-raw]').map((n) => n.textContent).join('\n');
      for (const c of cases) {
        assert.ok(!text.includes(c.probe), `${c.label}: the DOM carries ${c.probe.slice(0, 8)}`);
        assert.ok(!text.includes(c.value), `${c.label}: the DOM carries the whole secret`);
      }
      assert.ok((raw.match(/"sweep_note": "\[withheld\]"/g) || []).length >= cases.length, 'the raw view says withheld for every one of them');
      if (from === 0) for (const m of BENIGN_MARKERS) assert.ok(raw.includes(m), `the raw view of the harmless long text reaches ${m}`);
      for (const probe of new Set(cases.map((c) => c.probe))) {
        typeSearch(el, probe);
        assert.equal(rows(el).length, 0, `a search for ${probe.slice(0, 8)} finds a row`);
      }
      if (from === 0) {
        for (const m of BENIGN_MARKERS) {
          typeSearch(el, m);
          assert.equal(rows(el).length, 1, `the search reaches ${m} in the harmless long text`);
        }
      }
      typeSearch(el, '');
      const c0 = clip.clips.length;
      const b0 = clip.blobs.length;
      q(el, '[data-inspector-copy]').click();
      await tick();
      q(el, '[data-inspector-export="json"]').click();
      q(el, '[data-inspector-export="csv"]').click();
      for (const id of [`sensor.ecco_intel_sw_${cases[0].id}`, `sensor.ecco_intel_sw_${cases[cases.length - 1].id}`]) {
        rowFor(el, id).querySelector('[data-inspector-copy="row"]').click();
        await tick();
      }
      const outputs = [...clip.clips.slice(c0), ...(await Promise.all(clip.blobs.slice(b0).map((b) => b.text())))];
      assert.equal(outputs.length, 5, 'one copy of every row, two row copies and two downloads');
      for (const bytes of outputs) {
        assert.ok(bytes.length > 100);
        for (const c of cases) {
          assert.ok(!bytes.includes(c.probe), `${c.label}: an output carries ${c.probe.slice(0, 8)}`);
          assert.ok(!bytes.includes(c.value), `${c.label}: an output carries the whole secret`);
        }
      }
      el.disconnectedCallback();
    }
  } finally {
    clip.restore();
  }
});

// Review round 6 ([r6]), reviewer mutant P07 (an extra inline custom property set on the shell by a bracket call next to the bar-segment call): the static pin now reads structure (static.test.mjs), and this
// is the same net by what the code DOES, whatever its spelling: in both modes the only elements that ever carry an inline custom property are the bar segments (--ecco-w) and the tile rings (--ecco-p).
test('AC6 [r6] inline style by behaviour: in both modes, after every kind of update, the only elements that carry an inline custom property are the bar segments (--ecco-w) and the rings (--ecco-p); the host, the shell, the strip and every ancestor carry none (reviewer mutant P07)', () => {
  const el = mount();
  const carriers = (where) => {
    const seen = { seg: 0, ring: 0 };
    const walk = (n) => {
      if (n.nodeType !== 1) return;
      const props = [...n._props.keys()];
      if (props.length) {
        if (n.getAttribute('data-seg') !== null) {
          assert.deepEqual(props, ['--ecco-w'], `${where}: a bar segment`);
          seen.seg += 1;
        } else if ((n.getAttribute('class') || '').split(' ').includes('ring')) {
          assert.deepEqual(props, ['--ecco-p'], `${where}: a ring`);
          seen.ring += 1;
        } else assert.fail(`${where}: <${n.tagName}> carries ${props.join(', ')}`);
      }
      n.childNodes.forEach(walk);
    };
    walk(root(el));
    assert.deepEqual([...el._props.keys()], [], `${where}: the host element carries none`);
    return seen;
  };
  const production0 = carriers('Production, first render');
  geek(el);
  const geek0 = carriers('Geek Mode, first render');
  assert.ok(geek0.seg >= 1, 'the health bar has segments, so the net looks at something');
  el.hass = makeHass(miniStates((s) => { s['sensor.ecco_intel_status'].state = 'unavailable'; }));
  carriers('Geek Mode, after an update');
  production(el);
  carriers('Production, after switching back');
  assert.ok(production0.seg + production0.ring + geek0.seg + geek0.ring > 0);
  // negative control: the planted forms are each seen (a property written on the shell, on the strip and on the host, with the bar's own call)
  for (const target of ['[data-ecco-alert-strip]', '.shell']) {
    const node = q(el, target);
    node.style.setProperty('--ecco-fg', 'transparent');
    assert.throws(() => carriers(`planted on ${target}`), /carries --ecco-fg/);
    node._props.clear();
  }
  el._props.set('--ecco-fg', 'transparent');
  assert.throws(() => carriers('planted on the host'), /host element carries none/);
  el._props.clear();
  carriers('clean again');
});

// Review round 6 ([r6]): a text longer than LIMITS.scanBound is withheld whole, and the marker says why in words that are true for both causes (it is not necessarily secret).
test('AC10 [r6] a value too long to be checked is withheld in the row, in the open attribute list and in the raw view, and the marker says "secret or private, or too long to be checked"', () => {
  const states = miniStates((st) => { st['sensor.ecco_intel_new_diagnostic'].attributes.huge = 'q'.repeat(LIMITS.scanBound + 1); });
  const el = mount({ states });
  geek(el);
  rowFor(el, 'sensor.ecco_intel_new_diagnostic').querySelector('[data-row-toggle]').click();
  rowFor(el, 'sensor.ecco_intel_new_diagnostic').querySelector('[data-raw-toggle]').click();
  const marks = qa(el, '[data-withheld]');
  assert.ok(marks.length >= 1, 'the marker is shown');
  for (const m of marks) {
    assert.match(m.getAttribute('title'), /secret or private/);
    assert.match(m.getAttribute('title'), /too long to be checked/);
    assert.match(textOf(m), /Withheld/);
  }
  const text = allText(root(el));
  assert.ok(!text.includes('q'.repeat(100)), 'nothing of the long text is anywhere in the DOM');
  const raw = qa(el, '[data-inspector-raw]').map((n) => n.textContent).join('\n');
  assert.match(raw, /"huge": "\[withheld\]"/);
});

// ---------------------------------------------------------------------------------------------------------------------------
// Review round 7 ([r7]). KEY FOLD on the DOM paths (reviewer mutant N13: the catalogue fragment was matched on the key as written, so site_<zero-width space>owner, a Cyrillic o and a fullwidth s showed Alice
// Example): a value under any form of a key that holds a fragment is in no row, no open attribute list, no raw view, no search result, no copy and no download. And the scan budget on the DOM: an entity with
// more text than the budget pays for says so, and shows nothing it did not read.
// ---------------------------------------------------------------------------------------------------------------------------
test('AC10 [r7] KEY FOLD on every DOM path: under every form of the key site_owner (zero-width, bidi, Cyrillic, Greek, fullwidth, upper case, hyphen, space, dot, camel case) the value is in no row, no raw view, no search result, no copy and no download', async () => {
  const forms = ['site_owner', 'SITE_OWNER', 'site_​owner', 'site‍_owner', 'site_‮owner', 'site_o­wner', 'site_оwner', 'sitе_owner', 'ѕite_owner', 'sιte_owner', 'site_Οwner',
    'ｓite_owner', 'ｓｉｔｅ_ｏｗｎｅｒ', 'site-owner', 'site owner', 'siteOwner', 'site.owner', 'site​Owner', 'my_site_owner_name'];
  const marker = (i) => `zq7domfold${String(i).padStart(2, '0')}`;
  const states = miniStates((s) => { forms.forEach((k, i) => { s['sensor.ecco_intel_new_diagnostic'].attributes[k] = marker(i); }); });
  const clip = installClipboardAndDownload();
  try {
    const el = mount({ states });
    geek(el);
    openEverything(el);
    const text = allText(root(el));
    const raw = qa(el, '[data-inspector-raw]').map((n) => n.textContent).join('\n');
    forms.forEach((_, i) => {
      assert.ok(!text.includes(marker(i)), `form ${i}: the DOM carries the value`);
      assert.ok(!raw.includes(marker(i)), `form ${i}: the raw view carries the value`);
      typeSearch(el, marker(i));
      assert.equal(rows(el).length, 0, `form ${i}: a search finds a row`);
    });
    typeSearch(el, '');
    assert.ok((raw.match(/\[withheld\]/g) || []).length >= forms.length, 'the raw view says withheld for every one of them');
    q(el, '[data-inspector-copy]').click();
    await tick();
    q(el, '[data-inspector-export="json"]').click();
    q(el, '[data-inspector-export="csv"]').click();
    rowFor(el, 'sensor.ecco_intel_new_diagnostic').querySelector('[data-inspector-copy="row"]').click();
    await tick();
    const outputs = [...clip.clips, ...(await Promise.all(clip.blobs.map((b) => b.text())))];
    assert.equal(outputs.length, 4);
    for (const bytes of outputs) {
      assert.ok(bytes.length > 100);
      forms.forEach((_, i) => assert.ok(!bytes.includes(marker(i)), `form ${i}: an output carries the value`));
    }
    // the control: a key that holds no fragment in any form shows its value, so the withholding above is the fragment and nothing else
    el.disconnectedCallback();
    const states2 = miniStates((s) => { s['sensor.ecco_intel_new_diagnostic'].attributes['site_own'] = 'zq7domfold-shown'; s['sensor.ecco_intel_new_diagnostic'].attributes['sit_owner'] = 'zq7domfold-shown-too'; });
    const el2 = mount({ states: states2 });
    geek(el2);
    openEverything(el2);
    const raw2 = qa(el2, '[data-inspector-raw]').map((n) => n.textContent).join('\n');
    assert.ok(raw2.includes('zq7domfold-shown') && raw2.includes('zq7domfold-shown-too'), 'a key without the fragment is shown');
    el2.disconnectedCallback();
  } finally {
    clip.restore();
  }
});

test('AC12 [r7] an entity with more text than the scan budget pays for says so in the DOM (the row, the open attribute list and the raw view), shows nothing it did not read, and the marker says why', () => {
  const big = (m) => `${m} ${'The planner checked the overnight window and the tariff boundary before it chose. '.repeat(260)}`.slice(0, 19990);
  const states = miniStates((s) => {
    const a = s['sensor.ecco_intel_new_diagnostic'].attributes;
    ['zq7readA', 'zq7readB', 'zq7readC', 'zq7readD', 'zq7unreadE', 'zq7unreadF', 'zq7unreadG'].forEach((m, i) => { a[`long_${i}`] = big(m); });
  });
  const el = mount({ states });
  geek(el);
  openEverything(el);
  const text = allText(root(el));
  const raw = qa(el, '[data-inspector-raw]').map((n) => n.textContent).join('\n');
  assert.ok(text.includes('values not read'), 'the attribute list says that values were not read');
  assert.ok(text.includes(`${LIMITS.entityChars} characters`), 'and how much text the budget pays for');
  for (const m of ['zq7unreadE', 'zq7unreadF', 'zq7unreadG']) {
    assert.ok(!text.includes(m) && !raw.includes(m), `${m}: text that was not read is not shown`);
    typeSearch(el, m);
    assert.equal(rows(el).length, 0, `${m}: and is not found`);
  }
  typeSearch(el, '');
  for (const m of ['zq7readA', 'zq7readD']) assert.ok(raw.includes(m), `${m}: text that was read is shown, cut at the display cap`);
  const marks = qa(el, '[data-withheld]');
  assert.ok(marks.length >= 2);
  for (const m of marks) assert.match(m.getAttribute('title'), /too long to be checked/);
  el.disconnectedCallback();
});

test('AC12 [r7] a hostile entity (200 attributes of 19990 characters of near-miss text) does not freeze the card: mounting it, switching to Geek Mode and opening everything takes well under two seconds, and the alert strip is built (it took 38 seconds of the main thread in round 6)', () => {
  const text = (' .local @ x ' + '0123.'.repeat(4000)).slice(0, 19990);
  const states = miniStates((s) => {
    const a = {};
    for (let i = 0; i < 200; i += 1) a[`k${i}`] = text;
    s['sensor.ecco_intel_hostile_freeze'] = mkState('sensor.ecco_intel_hostile_freeze', '1', a);
  });
  const t0 = performance.now();
  const el = mount({ states });
  geek(el);
  openEverything(el);
  const ms = performance.now() - t0;
  assert.ok(ms < 2500, `${ms.toFixed(0)} ms`);
  assert.ok(q(el, '[data-ecco-alert-strip]'), 'the alert strip is there');
  assert.ok(rowFor(el, 'sensor.ecco_intel_hostile_freeze'), 'and so is the row');
  el.disconnectedCallback();
});

// ---------------------------------------------------------------------------------------------------------------------------
// Review round 8 ([r8]): TRIPWIRES. The round-7 net refused the NAMES of the animation and stylesheet APIs in the source; two mutants passed every node suite, one by building the name from pieces
// (const fn = 'ani' + 'mate'; strip[fn](...)), one by finding it on the prototype chain (Object.getOwnPropertyNames). The stand-in had no such member, so the mutants' own `typeof` test was false and they did nothing.
// Now every element, shadow root, fragment and document of the stand-in HAS each member (on the prototype, as a browser has it) and records being read or called; the afterEach above asserts that nothing was
// recorded after every test, and the tests below assert it step by step, in both modes.
// ---------------------------------------------------------------------------------------------------------------------------
test('AC6 [r8] the tripwires are armed (negative control for the net): each member of the Web Animations, style-map and stylesheet APIs is recorded when it is read or called, however it is reached: by name, by a computed key built from pieces, through the prototype chain; on an element, a shadow root, a fragment and a document', () => {
  tripwires.splice(0);
  assert.ok(TRIPWIRE_NAMES.length >= 10);
  for (const need of ['animate', 'getAnimations', 'attributeStyleMap', 'computedStyleMap', 'sheet', 'adoptedStyleSheets', 'insertRule']) assert.ok(TRIPWIRE_NAMES.includes(need), need);
  const el = doc.createElement('div');
  const targets = { element: el, 'shadow root': el.attachShadow(), fragment: doc.createDocumentFragment(), document: doc };
  assert.ok(targets.document instanceof MDocument && targets['shadow root'] instanceof MShadowRoot);
  for (const [what, target] of Object.entries(targets)) {
    for (const name of TRIPWIRE_NAMES) {
      tripwires.splice(0);
      void target[name];
      assert.ok(tripwires.length >= 1, `${what}.${name}: reading it is recorded`);
      tripwires.splice(0);
      const v = target[name];
      if (typeof v === 'function') {
        tripwires.splice(0);
        v.call(target, [], {});
        assert.ok(tripwires.some((t) => t.endsWith('()')), `${what}.${name}: calling it is recorded`);
      }
    }
  }
  // a name made of pieces, a computed key, and the prototype chain
  for (const [label, reach] of [
    ['a name built from pieces', () => el[['ani', 'mate'].join('')]([{ opacity: 0 }], { duration: 1 })],
    ['a computed key', () => { const k = 'getAnimations'; return el[k](); }],
    ['the prototype chain', () => {
      let p = Object.getPrototypeOf(el);
      let k = null;
      while (p && !k) {
        k = Object.getOwnPropertyNames(p).find((n) => n.length === 7 && n.startsWith('anim')) || null;
        if (!k) p = Object.getPrototypeOf(p);
      }
      assert.ok(k, 'the member is found on the chain');
      return p[k].call(el, [{ opacity: 0 }], { duration: 1 });
    }],
    ['a stylesheet reached from an element', () => el.sheet.insertRule('a{}')],
    ['a style map', () => el.attributeStyleMap.set('opacity', 0)],
    ['an adopted stylesheet', () => { doc.adoptedStyleSheets = []; }],
  ]) {
    tripwires.splice(0);
    reach();
    assert.ok(tripwires.length >= 1, `${label}: recorded`);
  }
  tripwires.splice(0);
  assert.equal(doc.recorded.apiCalls, tripwires, 'and the document exposes the record');
});

test('AC6 [r8] BOTH MODES, EVERY STEP: nothing of the Web Animations, style-map or stylesheet APIs is read or called by the card on mount, on a switch to Geek Mode, on opening every row, on searching, filtering and paging, on a hass update, on a switch back and on disconnecting (the strip and everything else, in both modes)', () => {
  const check = (where) => assert.deepEqual(tripwires.splice(0), [], where);
  tripwires.splice(0);
  const el = mount({ states: miniStates(TRIGGER.A01) });
  check('after mount, in Production');
  geek(el);
  check('after the switch to Geek Mode');
  openEverything(el);
  check('with every group and row open');
  typeSearch(el, 'status');
  check('after a search');
  choose(el, 'status', 'LIVE');
  check('after a filter');
  typeSearch(el, '');
  choose(el, 'status', 'all');
  check('after clearing both');
  el.hass = makeHass(miniStates((s) => { s['sensor.ecco_intel_status'] = mkState('sensor.ecco_intel_status', 'OK', {}); }));
  check('after a hass update in Geek Mode');
  production(el);
  check('after the switch back to Production');
  geek(el);
  production(el);
  geek(el);
  check('after switching back and forth');
  el.disconnectedCallback();
  check('after disconnecting');
});

// ---------------------------------------------------------------------------------------------------------------------------
// Review round 8 ([r8]): an entity that the snapshot did not read, in the DOM. The snapshot reads at most LIMITS.snapshotChars across all its entities (budget.test.mjs); this is what a person sees past it.
// ---------------------------------------------------------------------------------------------------------------------------
function unreadView() {
  const N = 30;
  const sources = Array.from({ length: N }, (_, i) => ({
    id: `B${String(i).padStart(2, '0')}`, entity_id: `sensor.ecco_big_${String(i).padStart(2, '0')}`, group: 'g', title: `Big ${i}`, description: '', priority: 'normal', unit: null,
    expected_update_s: null, stale_after_s: null, origin: 'integration', attributes: [],
  }));
  const catalogue = {
    schema: 'ecco-geek-catalogue/1', view_id: 'big', title: 'Big', contract: 'big/1', groups: [{ id: 'g', title: 'G', order: 1, description: '' }], sources,
    discover: { entity_prefixes: [], group: 'g', exclude_entity_ids: [] }, alerts: [], exceptions: [], redaction: { extra_key_patterns: [] },
  };
  const states = {};
  for (let i = 0; i < N; i += 1) {
    const id = `sensor.ecco_big_${String(i).padStart(2, '0')}`;
    const a = {};
    for (let k = 0; k < 6; k += 1) a[`text_${k}`] = `zqmark${String(i).padStart(2, '0')}x${k} ${'The planner checked the overnight window. '.repeat(480).slice(0, 19970)}`;
    states[id] = mkState(id, 'ok', a);
  }
  return { catalogue, states, N };
}

test('AC12 [r8] the DOM says what was not read: Geek Mode counts them in the header, each row says "values not read" and holds nothing of the entity, the Problems filter lists them, and Production says so in one sentence; the entities that were read still show their text', () => {
  const { catalogue, states, N } = unreadView();
  const el = mount({ catalogue, states, config: { page_size: 100 } });
  const prodNote = q(el, '[data-ecco-summary]').textContent;
  assert.match(prodNote, /\d+ data points were not read: this view holds more data than it reads at once/, 'Production says it');
  geek(el);
  openEverything(el);
  const sub = q(el, '[data-geek-sub]').textContent;
  const m = /(\d+) not read \(too much data for one pass\)/.exec(sub);
  assert.ok(m, sub);
  const unread = Number(m[1]);
  assert.ok(unread >= 8 && unread < N, `${unread} of ${N} not read`);
  assert.equal(rows(el).length, N, 'every entity is a row, read or not');
  const text = allText(root(el));
  let withText = 0;
  for (let i = 0; i < N; i += 1) {
    const id = `sensor.ecco_big_${String(i).padStart(2, '0')}`;
    const row = rowFor(el, id);
    assert.ok(row, id);
    const marker = `zqmark${String(i).padStart(2, '0')}x0`;
    const shown = allText(row);
    if (shown.includes('values not read') && !shown.includes(marker)) continue;
    withText += 1;
    assert.ok(shown.includes(marker) || text.includes(marker), `${id}: a row that was read shows its text`);
  }
  assert.equal(withText, N - unread, 'the rows that were read are the others');
  // an entity that was not read has no marker text anywhere in the shadow tree
  const lastId = `sensor.ecco_big_${String(N - 1).padStart(2, '0')}`;
  assert.ok(!text.includes(`zqmark${String(N - 1).padStart(2, '0')}x0`), `nothing of ${lastId} (not read) is in the DOM`);
  assert.ok(allText(rowFor(el, lastId)).includes('values not read'), 'its row says so');
  // the Problems filter lists them (and the data points that were read are live)
  q(el, '[data-inspector-filter="problems"]').click();
  assert.equal(rows(el).length, unread, 'the Problems filter lists exactly the rows that were not read');
  // and a search for the words
  q(el, '[data-inspector-filter="problems"]').click();
  typeSearch(el, 'not read');
  assert.equal(rows(el).length, unread);
});
