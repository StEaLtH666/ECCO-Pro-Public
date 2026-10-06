// Element tests on REAL node trees (test/minidom.mjs): in-place patching of card 7, focus, selection, scroll.
// element.test.mjs covers the service-call and timer behaviour against a string-level stub; this file covers
// what only a tree can show: that the nodes the user is holding on to (the register table's scroll region, a
// text selection, a focused control) are the same nodes after a render.
import test from 'node:test';
import assert from 'node:assert/strict';
import { installDom } from './minidom.mjs';
import { scenarios, IDS, T0, hassFor, statesFor, withStates, callsOf, touchedOf } from './helpers.mjs';

const dom = installDom();
const mod = await import('../ecco-fallback-recovery-card.js?dom');
const { EccoFallbackRecoveryCard, TAG, DETAIL_STORAGE_KEY, morphNode, setText, planPatch, CARD_DEFS } = mod;
const names = Object.keys(scenarios);

function makeCard(scenario = 'ready_diff', { detail = true, intent = null } = {}) {
  dom.store.clear();
  if (detail) dom.store.set(DETAIL_STORAGE_KEY, '1');
  const el = new EccoFallbackRecoveryCard();
  el._now = () => T0 + 5000; // a fixed clock keeps every render deterministic
  el.setConfig({ type: `custom:${TAG}`, entities: { ...IDS } });
  const h = hassFor(scenarios[scenario], T0);
  el.hass = h;
  // FB-B2 (CARD-08): an arm that is on is "for a save" only when THIS card switched it on; a test that wants the confirmation says so
  if (intent) {
    el._ui.intent = intent;
    el._renderCards();
  }
  return { el, h, root: el._root };
}

const template = (html) => {
  const t = dom.doc.createElement('template');
  t.innerHTML = html;
  return t;
};
// the 1 Hz tick fills the data-t placeholders in place, so a live tree is compared with them blanked
const blank = (s) => s.replace(/(<span[^>]*data-t="\w+"[^>]*>)[^<]*(<\/span>)/g, '$1$2');
const fresh = (html) => blank(template(html).innerHTML);
const same = (live, html) => blank(live) === fresh(html);
const inCard = (m, node) => node.contains(m.target);
// Nodes are never assertion operands: a failing assert.equal would try to print a whole (circular) tree.
const sameNode = (a, b, msg) => assert.ok(a === b, msg);
const otherNode = (a, b, msg) => assert.ok(a !== b, msg);
const structural = (muts) => muts.filter((m) => m.type === 'childList' || m.type === 'innerHTML').length;

// ---------------------------------------------------------------------------
test('the mini DOM parses and serialises the card markup (the base of every test below)', () => {
  const { el, root } = makeCard('ready_diff');
  for (const def of CARD_DEFS) {
    const live = root.getElementById(def.id);
    assert.ok(live, def.id);
    assert.ok(same(live.innerHTML, el._lastRender.cards[def.id].inner), `${def.id}: the live tree is the render`);
  }
  assert.equal(root.getElementById('c3').children.length, 6, 'the review card keeps its six kids');
  assert.equal(root.getElementById('c7').children.length, 2, 'card 7 has two kids: the eyebrow and the keyed body');
});

test('setText touches only the characters that changed (so a selection around them survives)', () => {
  const doc = dom.doc;
  const t = doc.createTextNode('st=CANDIDATE_READY;prior=VALID;exp=112;warn=-');
  doc.mutations.length = 0;
  assert.equal(setText(t, 'st=CANDIDATE_READY;prior=VALID;exp=102;warn=-'), true);
  const rd = doc.mutations.filter((m) => m.type === 'replaceData');
  assert.equal(rd.length, 1);
  assert.deepEqual([rd[0].offset, rd[0].count, rd[0].data], [t.nodeValue.indexOf('exp=1') + 5, 1, '0']);
  assert.equal(setText(t, t.nodeValue), false, 'identical text writes nothing');
  assert.equal(doc.mutations.filter((m) => m.type === 'replaceData').length, 1);
  // growth, shrinkage, and a completely different string
  assert.equal(setText(t, 'st=CANDIDATE_READY;prior=VALID;exp=92;warn=-') && t.nodeValue, 'st=CANDIDATE_READY;prior=VALID;exp=92;warn=-');
  assert.equal(setText(t, 'x') && t.nodeValue, 'x');
  assert.equal(setText(t, '') && t.nodeValue, '');
  assert.equal(setText(t, 'abc') && t.nodeValue, 'abc');
  // a range that spans the whole string stays on the whole string when only its middle changes
  const w = doc.createTextNode('aaa-112-bbb');
  const r = doc.createRange();
  r.setStart(w, 0);
  r.setEnd(w, w.nodeValue.length);
  setText(w, 'aaa-1002-bbb');
  assert.equal(r.toString(), 'aaa-1002-bbb');
  // a node without replaceData falls back to assigning the value
  const plain = { nodeValue: 'a' };
  assert.equal(setText(plain, 'b'), true);
  assert.equal(plain.nodeValue, 'b');
});

test('morphNode keeps nodes whose type and tag match, replaces the others, trims or extends the children', () => {
  const live = template('<div id="a" class="x"><p>one</p><span>two</span><b>gone</b></div>').content.firstElementChild;
  const [p, span] = live.children;
  const out = morphNode(live, template('<div id="a" class="y" data-n="1"><p>uno</p><i>new</i></div>').content.firstElementChild);
  sameNode(out, live, 'morphNode returns the kept node');
  sameNode(live.children[0], p, 'the matching <p> is the same node');
  assert.equal(p.firstChild.nodeValue, 'uno', 'its text is updated in place');
  otherNode(live.children[1], span, 'a different tag is replaced');
  assert.equal(live.children[1].nodeName, 'I');
  assert.equal(live.children.length, 2, 'the surplus <b> is removed');
  assert.equal(live.getAttribute('class'), 'y');
  assert.equal(live.getAttribute('data-n'), '1');
  const grown = morphNode(live, template('<div id="a" class="y" data-n="1"><p>uno</p><i>new</i><u>x</u><u>y</u></div>').content.firstElementChild);
  assert.equal(grown.children.length, 4, 'extra children are appended');
  const attrless = morphNode(live, template('<div id="a"><p>uno</p></div>').content.firstElementChild);
  assert.deepEqual(attrless.attributes, [{ name: 'id', value: 'a' }], 'attributes the new node lacks are removed');
  const swapped = template('<section><div id="q"></div></section>').content.firstElementChild;
  const q = swapped.children[0];
  assert.equal(morphNode(q, template('<span id="q"></span>').content.firstElementChild).nodeName, 'SPAN');
  assert.equal(swapped.children[0].nodeName, 'SPAN', 'a different root tag is replaced in its parent');
});

test('planPatch: keyed kids are patched in place (morph), live regions in place (live), everything else replaced', () => {
  const a = ['<div class="eyebrow">x</div>', '<div id="adv-body" data-morph="adv">1</div>', '<div class="live" data-live="head">h</div>'];
  assert.deepEqual(planPatch(a, a.slice()), ['keep', 'keep', 'keep']);
  assert.deepEqual(planPatch(a, ['<div class="eyebrow">y</div>', '<div id="adv-body" data-morph="adv">2</div>', '<div class="live" data-live="head">i</div>']), ['replace', 'morph', 'live']);
  assert.deepEqual(planPatch(a, [a[0], '<p class="sentence" data-morph="adv">c</p>', a[2]]), ['keep', 'morph', 'keep'], 'same key, different tag: morph decides (it replaces the node)');
  assert.deepEqual(planPatch(a, [a[0], '<div data-morph="other">2</div>', a[2]]), ['keep', 'replace', 'keep'], 'a different key is a replace');
});

// ---------------------------------------------------------------------------
test('card 7 is patched in place on a B3 publish: table node, scroll position and a text selection survive', () => {
  const { el, root } = makeCard('ready_diff');
  const c7 = root.getElementById('c7');
  const scroll = c7.querySelector('[data-fk="scroll-regs"]');
  const table = scroll.querySelector('table');
  const row = table.querySelector('tbody').children[3];
  const code = c7.querySelector('[data-raw="review"]');
  const text = code.firstChild;
  assert.equal(scroll.getAttribute('role'), 'region');
  scroll.scrollLeft = 120;
  const sel = dom.doc.createRange();
  sel.setStart(text, 0);
  sel.setEnd(text, text.nodeValue.length);
  assert.match(text.nodeValue, /exp=112;/);

  dom.doc.mutations.length = 0;
  // the firmware re-publishes B3 with a smaller exp (what happens every 10 s while a candidate exists)
  el.hass = hassFor({ ...scenarios.ready_diff, review: scenarios.ready_diff.review.replace('exp=112', 'exp=102') }, T0 + 10_000);

  sameNode(root.getElementById('c7'), c7, 'the card section is the same element');
  sameNode(c7.querySelector('[data-fk="scroll-regs"]'), scroll, 'the scroll region is the same node');
  sameNode(scroll.querySelector('table'), table, 'the table is the same node');
  sameNode(table.querySelector('tbody').children[3], row, 'a row is the same node');
  sameNode(c7.querySelector('[data-raw="review"]'), code, 'the raw-string element is the same node');
  sameNode(code.firstChild, text, 'the text node holding the raw B3 string is the same node');
  assert.equal(scroll.scrollLeft, 120, 'the horizontal scroll position is kept');
  assert.match(text.nodeValue, /exp=102;/, 'and the raw string shows the new value');
  assert.equal(sel.toString(), text.nodeValue, 'a selection of the whole raw string still selects it');
  const mine = dom.doc.mutations.filter((m) => inCard(m, c7));
  assert.equal(structural(mine), 0, 'no node was added, removed or rebuilt');
  const rd = mine.filter((m) => m.type === 'replaceData');
  assert.equal(rd.length, 1, 'exactly one character range was rewritten');
  assert.deepEqual([rd[0].count, rd[0].data], [1, '0']);
  assert.ok(same(c7.innerHTML, el._lastRender.cards.c7.inner), 'and the patched tree equals a fresh render');
});

test('card 7 keeps its nodes across a state change that rewrites the table (candidate -> expired)', () => {
  const { el, root } = makeCard('ready_diff');
  const c7 = root.getElementById('c7');
  const scroll = c7.querySelector('[data-fk="scroll-regs"]');
  const tbody = scroll.querySelector('tbody');
  const cells = [...tbody.querySelectorAll('td')];
  scroll.scrollLeft = 64;
  dom.doc.mutations.length = 0;
  el.hass = hassFor(scenarios.expired, T0 + 20_000);
  sameNode(c7.querySelector('[data-fk="scroll-regs"]'), scroll, 'the scroll region is the same node');
  sameNode(scroll.querySelector('tbody'), tbody, 'the table body is the same node');
  assert.equal([...tbody.querySelectorAll('td')].length, cells.length);
  assert.ok([...tbody.querySelectorAll('td')].every((td, i) => td === cells[i]), 'every table cell is the same node');
  assert.equal(scroll.scrollLeft, 64);
  const mine = dom.doc.mutations.filter((m) => inCard(m, c7));
  assert.equal(mine.filter((m) => m.type === 'innerHTML').length, 0, 'nothing was rebuilt through innerHTML');
  // a cell may swap its mark (a check mark span becomes a dash); no table, body or row node is ever added or removed
  const outside = mine.filter((m) => m.type === 'childList' && !['TD'].includes(m.target.nodeName));
  assert.equal(outside.length, 0, 'only cell contents changed, never the table structure');
  assert.ok(same(c7.innerHTML, el._lastRender.cards.c7.inner));
  // the obligation-vector rows (six entries to one "none yet" row) are the only structural change allowed
  el.hass = hassFor({ ...scenarios.expired, review: scenarios.expired.review.replace(/obl=[^;]*/, 'obl=-') }, T0 + 30_000);
  sameNode(c7.querySelector('[data-fk="scroll-regs"]'), scroll, 'the scroll region survives a vector of a different length');
  assert.ok(same(c7.innerHTML, el._lastRender.cards.c7.inner));
});

test('keyboard focus on a scroll region is not lost: kept when the node is kept, restored by data-fk when it is replaced', () => {
  const { el, root } = makeCard('ready_diff');
  const regs = root.getElementById('c7').querySelector('[data-fk="scroll-regs"]');
  regs.focus();
  sameNode(root.activeElement, regs, 'the region took focus');
  el.hass = hassFor({ ...scenarios.ready_diff, review: scenarios.ready_diff.review.replace('exp=112', 'exp=102') }, T0 + 10_000);
  sameNode(root.activeElement, regs, 'card 7 is patched in place, so focus never moves');

  // card 6 swaps its whole body when the candidate goes away (candidate view -> saved view): its slot table is a
  // NEW node, and focus comes back to the equivalent region instead of falling to the page
  const slots = root.getElementById('c6').querySelector('[data-fk="scroll-slots"]');
  slots.focus();
  sameNode(root.activeElement, slots, 'the slot table took focus');
  el.hass = hassFor(scenarios.expired, T0 + 20_000);
  const slots2 = root.getElementById('c6').querySelector('[data-fk="scroll-slots"]');
  assert.ok(slots2 && slots2.getAttribute('role') === 'region');
  otherNode(slots2, slots, 'the card 6 table was rebuilt');
  sameNode(root.activeElement, slots2, 'and focus was restored to it');
});

test('the technical-detail toggle collapses and expands card 7 without breaking the tree, and aria-controls follows the region', () => {
  const { el, root } = makeCard('ready_diff', { detail: true });
  const c7 = root.getElementById('c7');
  const toggle = () => c7.querySelector('[data-act="toggle-detail"]');
  assert.equal(toggle().getAttribute('aria-expanded'), 'true');
  assert.equal(toggle().getAttribute('aria-controls'), 'adv-body');
  assert.ok(root.getElementById('adv-body'), 'the controlled region exists');
  toggle().focus();
  el._act('toggle-detail');
  assert.equal(toggle().getAttribute('aria-expanded'), 'false');
  assert.equal(toggle().hasAttribute('aria-controls'), false, 'no aria-controls while the region does not exist');
  assert.ok(root.getElementById('adv-body') === null, 'the controlled region is gone');
  sameNode(root.activeElement, toggle(), 'focus stays on the toggle');
  assert.ok(same(c7.innerHTML, el._lastRender.cards.c7.inner));
  el._act('toggle-detail');
  assert.equal(toggle().getAttribute('aria-controls'), 'adv-body');
  assert.ok(root.getElementById('adv-body'));
  assert.ok(same(c7.innerHTML, el._lastRender.cards.c7.inner));
});

test('an identical render, and a publish that changes nothing the card shows, touch no node at all', () => {
  const { el } = makeCard('ready_diff');
  dom.doc.mutations.length = 0;
  // same state strings, newer last_changed on an entity whose state did not change: a full re-render, zero DOM writes
  const E = { ...scenarios.ready_diff };
  const h = hassFor(E, T0);
  h.states[IDS.last_result] = { ...h.states[IDS.last_result], last_changed: new Date(T0 + 4000).toISOString() };
  el.hass = h;
  assert.deepEqual(dom.doc.mutations, [], 'no childList, text, attribute or innerHTML mutation');
});

test('after any scenario-to-scenario transition every card equals a fresh render (patching is lossless)', () => {
  // FB-B2: 65 scenarios. The open-detail state (card 7's body is rendered) is checked on every pair, on every card.
  // FB-B2 (AW-4), before: the closed state was walked on every fifth pair only ("it only differs in card 7's one-line body"), so card 7's closed
  // patching was checked on a fifth of the pairs and the walk was a different walk, not a subset. Now the closed state walks EVERY pair too,
  // and card 7 - the only card the detail state changes - is compared on every one of them; the other seven cards are compared on every fifth
  // pair in the closed walk (the open walk already compares all eight cards on every pair, and they do not depend on the detail state).
  const c7Only = CARD_DEFS.filter((def) => def.id === 'c7');
  let c7Compared = 0;
  for (const detail of [true, false]) {
    for (const [fi, from] of names.entries()) {
      const { el, root } = makeCard(from, { detail });
      let n = 0;
      for (const [ti, to] of names.entries()) {
        n += 1;
        el.hass = hassFor(scenarios[to], T0 + n * 1000);
        // this test never reads the mutation log, and the log holds every node it ever touched (detached
        // trees included): left to grow over ~3,900 renders it needs ~3.7 GB and a CI runner's heap runs out
        dom.doc.mutations.length = 0;
        const defs = detail || (fi + ti) % 5 === 0 ? CARD_DEFS : c7Only;
        for (const def of defs) {
          assert.ok(same(root.getElementById(def.id).innerHTML, el._lastRender.cards[def.id].inner), `${detail ? 'open' : 'closed'} ${from} -> ${to}: ${def.id}`);
          if (!detail && def.id === 'c7') c7Compared += 1;
        }
      }
    }
  }
  assert.equal(c7Compared, names.length * names.length, 'card 7 was compared on every pair in the closed state');
});

test('the card never touched a hass member outside states / locale / config / language / callService', () => {
  const { el, h } = makeCard('ready_diff');
  const calls = callsOf(h);
  for (const act of ['review', 'toggle-detail', 'view', 'more-info', 'goto-summary']) {
    try { el._act(act, { view: 'saved', ent: 'profile_state' }); } catch (e) { /* a refusal is fine */ }
  }
  el.hass = hassFor(scenarios.reading, T0 + 1000);
  assert.deepEqual(touchedOf(h), []);
  assert.deepEqual(touchedOf(el.hass), []);
  assert.ok(calls.every((c) => c.domain === 'button' && c.service === 'press' && c.data.entity_id === IDS.review_button));
  el.disconnectedCallback();
});

// ---------------------------------------------------------------------------
// FB-B2: guarded Save / Invalidate on real trees
// ---------------------------------------------------------------------------
const RID = '5F3A9C21B04E7D18';
const PID = '2BAEBFE97F4E04BC';
const SUBJECTS = names.filter((n) => /^(arm_|ready_|idle_saved|saving|saved_|save_|invalidate|invalidated|action_refused|not_captured_cand)/.test(n));
/** The same hass with another state map, sharing the call log (Home Assistant replaces the hass object on every change). */
const republish = (el, h, name, patch = {}, stamps = {}) => {
  const E = { ...scenarios[name], ...patch };
  const next = withStates(h, statesFor(E, T0, null, stamps));
  el.hass = next;
  return next;
};
const clickAll = (root, panel) => {
  root.click(panel);
  root.click(panel.querySelector('.ctitle'));
  root.click(panel.querySelector('.sentence'));
  root.click(panel.querySelector('.checks'));
};

test('FB-B2 a click on the real button sends one call; a script-made or flagless event sends nothing; its icon works like the button', () => {
  const { el, h, root } = makeCard('arm_on_ready', { intent: 'save' });
  const save = () => root.getElementById('c4').querySelector('[data-act="save"]');
  assert.ok(save(), 'the confirmation panel is on screen');
  assert.equal(save().getAttribute('data-id'), RID);
  for (const init of [{ isTrusted: false }, {}, { isTrusted: 'true' }, { isTrusted: undefined }]) root.click(save(), init);
  assert.deepEqual(callsOf(h), [], 'events that a script dispatched or that carry no flag are ignored');
  root.click(save().querySelector('svg'), { isTrusted: false });
  assert.deepEqual(callsOf(h), []);
  root.click(save().querySelector('svg'));
  assert.deepEqual(callsOf(h), [{ domain: 'esphome', service: 'ecco_clock_dongle_fallback_profile_execute', data: { action: 'SAVE', target_id: RID, confirmation: `SAVE ${RID}` } }]);
  // the request is on its way: the panel and its buttons are gone, so a second click cannot even be made
  assert.equal(root.getElementById('c4').querySelector('[data-act="save"]'), null);
  assert.equal(root.getElementById('c4').querySelector('[data-act="arm-cancel"]'), null);
  assert.match(root.getElementById('c4').innerHTML, /SAVE REQUESTED/);
  el.disconnectedCallback();
  // Cancel is a click too: it turns the arm off and nothing else
  const c = makeCard('arm_on_ready', { intent: 'save' });
  c.root.click(c.root.getElementById('c4').querySelector('[data-act="arm-cancel"]'));
  assert.deepEqual(callsOf(c.h), [{ domain: 'switch', service: 'turn_off', data: { entity_id: IDS.arm } }]);
  c.el.disconnectedCallback();
});

test('FB-B2 a disabled-looking button is not the guard: clicking it re-validates and sends nothing', () => {
  for (const [name, act] of [['ready_nosup', 'arm'], ['not_saveable', 'arm'], ['arm_unavailable', 'arm']]) {
    const { el, h, root } = makeCard(name);
    const btn = root.getElementById('c4').querySelector(`[data-act="${act}"]`);
    assert.equal(btn.getAttribute('aria-disabled'), 'true', name);
    root.click(btn);
    assert.deepEqual(callsOf(h), [], name);
    el.disconnectedCallback();
  }
  const { el, h, root } = makeCard('arm_on_ready', { intent: 'save' });
  republish(el, h, 'arm_on_ready', { ntp_synced: 'off' });
  const save = root.getElementById('c4').querySelector('[data-act="save"]');
  assert.equal(save.getAttribute('aria-disabled'), 'true');
  root.click(save);
  assert.deepEqual(callsOf(h), []);
  el.disconnectedCallback();
});

test('FB-B2 clicks inside a confirmation panel or a result block never open the more-info dialog; a click on the card text still does', () => {
  const { el, root } = makeCard('idle_saved');
  const events = [];
  el.dispatchEvent = (e) => events.push(e);
  const c1 = root.getElementById('c1');
  const block = c1.querySelector('.actblock');
  root.click(block);
  root.click(block.querySelector('.caption'));
  assert.deepEqual(events, [], 'the Invalidate control block is inert for the card tap');
  root.click(c1.querySelector('.sentence'));
  assert.equal(events.length, 1, 'a tap on the card text still opens the profile entity');
  assert.equal(events[0].type, 'hass-more-info');
  el.disconnectedCallback();
  const armed = makeCard('arm_on_no_candidate');
  armed.el._ui.intent = 'invalidate';
  armed.el._renderCards();
  const evs = [];
  armed.el.dispatchEvent = (e) => evs.push(e);
  const panel = armed.root.getElementById('c1').querySelector('.confirm');
  assert.ok(panel, 'the invalidate confirmation is open');
  clickAll(armed.root, panel);
  assert.deepEqual(evs, []);
  assert.equal(callsOf(armed.h).length, 0, 'clicking the panel text sends nothing');
  armed.el.disconnectedCallback();
});

test('FB-B2 focus: Arm moves focus to the confirmation heading once it exists, Cancel puts it back; a replaced Save button keeps focus', () => {
  const { el, h, root } = makeCard('ready_match');
  const armBtn = () => root.getElementById('c4').querySelector('[data-act="arm"]');
  armBtn().focus();
  root.click(armBtn());
  assert.equal(callsOf(h).length, 1);
  let next = republish(el, h, 'ready_match', { arm: 'on' }, { arm: T0 });
  const title = root.getElementById('confirm-save-title');
  assert.ok(title, 'the panel exists once the switch reports on');
  sameNode(root.activeElement, title, 'focus is on the heading: not on Save, not lost');
  assert.equal(title.getAttribute('tabindex'), '-1');
  // a re-render that replaces card 4's markup (the candidate countdown passes 45 s) keeps focus on the Save button by its focus key
  const save = () => root.getElementById('c4').querySelector('[data-act="save"]');
  save().focus();
  const before = save();
  el._now = () => T0 + 50_000;
  el._renderCards();
  assert.ok(save());
  otherNode(save(), before, 'the card markup was replaced');
  sameNode(root.activeElement, save(), 'focus followed the data-fk');
  // Cancel returns focus to Arm Save
  root.click(root.getElementById('c4').querySelector('[data-act="arm-cancel"]'));
  next = republish(el, next, 'ready_match', { arm: 'off' });
  sameNode(root.activeElement, armBtn(), 'back on the button that started it');
  el.disconnectedCallback();
});

test('FB-B2 a tick while the confirmation is open touches only the time placeholders: every button and row is the same node', () => {
  const { el, root } = makeCard('arm_on_ready', { intent: 'save' });
  const c4 = root.getElementById('c4');
  const save = c4.querySelector('[data-act="save"]');
  const cancel = c4.querySelector('[data-act="arm-cancel"]');
  const rows = c4.querySelector('.confirm').querySelector('.rows');
  const checks = [...c4.querySelectorAll('.check')];
  const arm = () => c4.querySelector('.armcount').querySelector('[data-t="arm"]');
  assert.equal(arm().textContent, '1:55');
  dom.doc.mutations.length = 0;
  for (const s of [6, 7, 8]) {
    el._now = () => T0 + s * 1000;
    el._renderCards();
  }
  sameNode(c4.querySelector('[data-act="save"]'), save, 'the Save button is the same node');
  sameNode(c4.querySelector('[data-act="arm-cancel"]'), cancel);
  sameNode(c4.querySelector('.confirm').querySelector('.rows'), rows);
  assert.ok([...c4.querySelectorAll('.check')].every((n, i) => n === checks[i]), 'every prerequisite row is the same node');
  assert.equal(arm().textContent, '1:52', 'the arm countdown was written in place');
  const muts = dom.doc.mutations.filter((m) => inCard(m, c4));
  assert.ok(muts.length > 0);
  assert.ok(muts.every((m) => m.target.nodeName === 'SPAN' && m.target.hasAttribute('data-t')), `only the placeholders were written: ${muts.map((m) => m.target.nodeName).join()}`);
  el.disconnectedCallback();
});

test('FB-B2 patching stays lossless across the Save and Invalidate states, with and without an intent and a request on its way', () => {
  const flow = (kind, state) => ({ kind, state, id: kind === 'save' ? RID : PID, variant: 'save', gen: 8, effectKind: 'replace', replaces: null, atMs: T0, review0: 'ready', b9Key: 'b', armOn: true });
  const ui = [
    {}, { intent: 'save' }, { intent: 'invalidate' }, { intent: 'sent' }, { intent: 'save', armPending: true }, { intent: 'invalidate', armPending: true },
    { intent: 'save', cancelling: true }, { flow: flow('save', 'sent') }, { flow: flow('save', 'running') }, { flow: flow('save', 'timeout') },
    { flow: flow('save', 'unsure') }, { flow: flow('invalidate', 'sent') }, { flow: flow('invalidate', 'timeout') },
  ];
  for (const from of ['ready_match', 'arm_on_ready', 'idle_saved']) {
    const { el, h, root } = makeCard(from);
    let cur = h;
    for (const to of SUBJECTS) {
      cur = republish(el, cur, to, {}, { arm: T0 });
      for (const u of ui) {
        el._ui.intent = u.intent || null;
        el._ui.flow = u.flow || null;
        el._armPendingUntil = u.armPending ? T0 + 60_000 : 0;
        el._cancelUntil = u.cancelling ? T0 + 60_000 : 0;
        el._renderCards();
        dom.doc.mutations.length = 0;
        for (const def of CARD_DEFS) {
          assert.ok(same(root.getElementById(def.id).innerHTML, el._lastRender.cards[def.id].inner), `${from} -> ${to} ${JSON.stringify(Object.keys(u))}: ${def.id}`);
        }
      }
    }
    el._ui.intent = null;
    el._ui.flow = null;
    el.disconnectedCallback();
  }
});

// ---------------------------------------------------------------------------
// FB-B2 card-fix: CARD-12 focus hand-over, CARD-08 strip on a real tree
// ---------------------------------------------------------------------------
test('FB-B2 CARD-12: the progress row that holds the focus is replaced by the outcome, and the focus moves to the result heading (never to the page, never to a button)', () => {
  const { el, h, root } = makeCard('arm_on_ready', { intent: 'save' });
  const c4 = () => root.getElementById('c4');
  const save = c4().querySelector('[data-act="save"]');
  assert.ok(save);
  root.click(save);
  const row = c4().querySelector('[data-fk="flow-status"]');
  assert.ok(row, 'the progress row exists');
  sameNode(root.activeElement, row, 'a click on Save puts the focus on the progress row');
  // the dongle accepts: another progress row replaces it, and the focus follows by its key
  let cur = republish(el, h, 'saving');
  sameNode(root.activeElement, c4().querySelector('[data-fk="flow-status"]'), 'SAVING: the focus stays on the progress row');
  // the outcome replaces the progress row: before the fix the focus fell to <body> and the keyboard lost its place
  cur = republish(el, cur, 'saved_ok');
  assert.equal(c4().querySelector('[data-fk="flow-status"]'), null, 'the progress row is gone');
  const head = c4().querySelector('[data-fk="act-result"]');
  assert.ok(head, 'the result heading is on screen');
  sameNode(root.activeElement, head, 'the focus moved to the result heading');
  assert.equal(head.getAttribute('tabindex'), '-1');
  assert.match(head.textContent, /SAVED/);
  assert.equal(root.activeElement.nodeName, 'DIV', 'not a button: nothing destructive is focused');
  assert.equal(el._focusKey, null, 'the focus request was served');
  el.disconnectedCallback();

  // a refusal: the same hand-over, to the refusal heading
  const r = makeCard('arm_on_ready', { intent: 'save' });
  r.root.click(r.root.getElementById('c4').querySelector('[data-act="save"]'));
  republish(r.el, r.h, 'save_refused_arm');
  sameNode(r.root.activeElement, r.root.getElementById('c4').querySelector('[data-fk="act-result"]'));
  assert.match(r.root.activeElement.textContent, /SAVE REFUSED/);
  r.el.disconnectedCallback();

  // the operator moved on (the focus is on Review): the card does not take it back
  const m = makeCard('arm_on_ready', { intent: 'save' });
  m.root.click(m.root.getElementById('c4').querySelector('[data-act="save"]'));
  const review = m.root.getElementById('c3').querySelector('[data-act="review"]');
  review.focus();
  republish(m.el, m.h, 'saved_ok');
  sameNode(m.root.activeElement, m.root.getElementById('c3').querySelector('[data-act="review"]'), 'the focus stays where the operator put it');
  m.el.disconnectedCallback();

  // no answer after 30 s: the progress row gives way to the "no result yet" message and the focus goes to the card heading
  const t = makeCard('arm_on_ready', { intent: 'save' });
  t.root.click(t.root.getElementById('c4').querySelector('[data-act="save"]'));
  sameNode(t.root.activeElement, t.root.getElementById('c4').querySelector('[data-fk="flow-status"]'));
  t.el._now = () => T0 + 5000 + 31_000;
  t.el._update();
  assert.equal(t.el._ui.flow.state, 'timeout');
  sameNode(t.root.activeElement, t.root.getElementById('c4').querySelector('[data-fk="act-result"]'), 'the timeout message does not strand the focus either');
  t.el.disconnectedCallback();
});

test('FB-B2 CARD-12: an invalidate result takes the focus the same way (the result block, or the card heading when there is none)', () => {
  const { el, h, root } = makeCard('arm_on_no_candidate', { intent: 'invalidate' });
  const c1 = () => root.getElementById('c1');
  root.click(c1().querySelector('[data-act="invalidate"]'));
  sameNode(root.activeElement, c1().querySelector('[data-fk="flow-status"]'), 'the progress row holds the focus');
  republish(el, h, 'invalidated_ok');
  assert.equal(c1().querySelector('[data-fk="flow-status"]'), null);
  sameNode(root.activeElement, c1().querySelector('[data-fk="act-result-inv"]'), 'the focus is on the result');
  assert.match(root.activeElement.textContent, /INVALIDATED/);
  el.disconnectedCallback();
  // a timeout has no result block: the fallback is the card's own heading
  const t = makeCard('arm_on_no_candidate', { intent: 'invalidate' });
  t.root.click(t.root.getElementById('c1').querySelector('[data-act="invalidate"]'));
  t.el._now = () => T0 + 5000 + 31_000;
  t.el._update();
  assert.equal(t.el._ui.flow.state, 'timeout');
  assert.equal(t.root.getElementById('c1').querySelector('[data-fk="act-result-inv"]'), null);
  sameNode(t.root.activeElement, t.root.getElementById('c1').querySelector('[data-fk="c1-head"]'));
  t.el.disconnectedCallback();
});

test('FB-B2 CARD-08: on a real tree an arm that is on without an Arm click shows the strip and no Save button; its Turn arm off sends one turn_off', () => {
  const { el, h, root } = makeCard('arm_on_ready');
  const c4 = () => root.getElementById('c4');
  assert.equal(c4().querySelector('[data-act="save"]'), null, 'no Save button for an arm this card did not switch on');
  assert.equal(c4().querySelector('.confirm'), null);
  const strip = c4().querySelector('.armstrip');
  assert.ok(strip);
  assert.match(strip.textContent, /Arm was turned on elsewhere\./);
  root.click(strip.querySelector('[data-act="arm-cancel"]'));
  assert.deepEqual(callsOf(h), [{ domain: 'switch', service: 'turn_off', data: { entity_id: IDS.arm } }]);
  el.disconnectedCallback();
});
