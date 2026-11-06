// Rendered markup over the six golden fixtures: exact copy, the null rule in the markup, the guards, escaping, structure.
import test from 'node:test';
import assert from 'node:assert/strict';
import { card, ids, cfg, env, statesFor, nowFor, render, renderFixture, textOf, withoutHistory, FIGURE_RE, fixtureNumbers,
  FIXTURES, NULL_FIXTURES } from './helpers.mjs';
import { fragment } from './minidom.mjs';

const figs = (html) => fragment(html).querySelectorAll('[data-fig]');

test('status copy: the pill, the callout title and body are exactly the text table for each fixture', () => {
  for (const name of FIXTURES) {
    const { vm, html } = renderFixture(name);
    const root = fragment(html);
    const copy = card.STATUS_COPY[vm.status];
    assert.equal(root.querySelector('[data-pill]').textContent, copy.pill, name);
    const call = root.querySelector(`[data-callout="${vm.status}"]`);
    if (copy.title === null) assert.equal(call, null, name);
    else {
      assert.equal(call.querySelector('h3').textContent, copy.title, name);
      assert.equal(call.querySelector('p').textContent, copy.body, name);
    }
  }
});

test('every recognised state shows the SHADOW banner and badge and the report age', () => {
  for (const name of FIXTURES) {
    const root = fragment(renderFixture(name).html);
    assert.equal(root.querySelector('[data-sec="banner"]').textContent, 'SHADOW MODE - advice only, nothing is applied', name);
    assert.equal(root.querySelector('[data-badge="shadow"]').textContent, 'SHADOW', name);
    assert.match(root.querySelector('[data-age]').textContent, /^Report from .+, 2 min ago( · next refresh \d\d:\d\d)?$/, name);
  }
});

test('null rule (markup): no figure and no item value under STALE / PAUSED / SELF_TEST_FAILED / STARTING', () => {
  for (const name of NULL_FIXTURES) {
    const { html } = renderFixture(name);
    const outside = withoutHistory(html);
    assert.equal(figs(outside).length, 0, `${name}: a data-fig outside the history block`);
    assert.doesNotMatch(textOf(outside), FIGURE_RE, `${name}: a number with a unit outside the history block`);
    assert.equal(fragment(outside).querySelectorAll('[data-item]').length, 0, `${name}: an item row`);
    for (const n of fixtureNumbers(name)) {
      const s = card.figure(n, '%').replace('%', '');
      assert.ok(!new RegExp(`(^|[^\\d.])${s.replace('.', '\\.')}(?:\\.0)?\\s*(%|kWh)`).test(textOf(outside)), `${name}: ${n}`);
    }
  }
});

test('null rule (markup): last_good appears only as labelled, collapsed history with its time', () => {
  const { html } = renderFixture('stale');
  const root = fragment(html);
  const h = root.querySelectorAll('[data-history]');
  assert.equal(h.length, 1);
  assert.equal(h[0].tagName, 'details');
  assert.equal(h[0].hasAttribute('open'), false, 'collapsed by default');
  assert.equal(h[0].querySelector('summary').textContent, `History: last good result from ${env.dateTime(Date.parse('2030-01-15T21:00:00+00:00'))}`);
  assert.match(h[0].textContent, /Not current advice/);
  assert.match(h[0].textContent, /Next charge target: 80%/);
  assert.equal(h[0].querySelectorAll('[data-fig]').length, 0, 'history values are not figures of the current result');
  for (const name of ['paused', 'self_test_failed', 'starting', 'synthetic_ok', 'all_open_blocked']) {
    assert.equal(fragment(renderFixture(name).html).querySelectorAll('[data-history]').length, 0, name);
  }
});

test('all decisions OPEN (all_open_blocked): no figure, "No advice" with the blocker texts, every I-D label listed', () => {
  const { vm, html } = renderFixture('all_open_blocked');
  const root = fragment(html);
  assert.equal(figs(html).length, 0);
  assert.doesNotMatch(textOf(html), FIGURE_RE);
  const ct = root.querySelector('[data-item="charge_target"]');
  assert.equal(ct.querySelector('[data-noadvice]').textContent, 'No advice');
  const texts = ct.querySelectorAll('li').map((li) => li.textContent);
  assert.deepEqual(texts, vm.items[0].blockers.map((b) => b.text));
  assert.equal(texts.length, 5);
  assert.match(texts[0], /^I-D1 \(Canonical soft planning floor\) is OPEN/);
  const drill = root.querySelector('details[data-k="drill"]');
  for (let i = 1; i <= 9; i += 1) assert.match(drill.textContent, new RegExp(`I-D${i} .+: OPEN`));
  assert.equal(root.querySelector('[data-tariff="unverified"]').textContent, 'Tariff not verified');
  assert.equal(root.querySelector('[data-sec="value"]'), null);
  for (const k of ['overnight_demand', 'export_event', 'dump_to_grid', 'predicted_day_load', 'predicted_morning_soc']) {
    const row = root.querySelector(`[data-item="${k}"]`);
    assert.equal(row.getAttribute('data-status'), 'BLOCKED', k);
    assert.match(row.textContent, /Blocked/, k);
  }
  assert.match(root.querySelector('[data-item="pv_tomorrow"]').textContent, /Not enough data/);
});

test('synthetic_ok: the figures, the bands, "~" on predicted figures, the shadow-advice label and the drill-down', () => {
  const { html } = renderFixture('synthetic_ok');
  const root = fragment(html);
  const fig = (k) => root.querySelector(`[data-fig="${k}"]`);
  assert.equal(fig('charge_target').textContent, '80%');
  assert.ok(fig('charge_target').classList.contains('rec'));
  assert.match(root.querySelector('[data-item="charge_target"]').textContent, /shadow advice, not applied/);
  assert.match(root.querySelector('[data-item="charge_target"]').textContent, /limited by DEMAND/);
  assert.equal(fig('overnight_demand').textContent, '~6.4 kWh');
  assert.equal(fig('predicted_day_load').textContent, '~14.2 kWh');
  assert.equal(root.querySelector('[data-band="predicted_day_load"]').textContent, '(11.0 kWh to 17.5 kWh)');
  assert.equal(fig('pv_tomorrow').textContent, '~9.8 kWh');
  assert.equal(root.querySelector('[data-band="pv_tomorrow"]').textContent, '(6.1 kWh to 12.4 kWh)');
  assert.equal(fig('predicted_morning_soc').textContent, '~72%');
  assert.ok(fig('predicted_morning_soc').classList.contains('pred'));
  assert.equal(fig('export_event'), null);
  assert.equal(fig('dump_to_grid'), null);
  assert.match(root.querySelector('[data-item="export_event"]').textContent, /No advice/);
  assert.match(root.querySelector('[data-item="dump_to_grid"]').textContent, /Not enough data/);
  assert.equal(root.querySelector('[data-dq]').textContent, 'OK');
  assert.match(root.querySelector('[data-sec="quality"]').textContent, /battery\.soc 40 s old \(limit 900 s\), fresh/);
  const drill = root.querySelector('details[data-k="drill"]');
  assert.equal(drill.hasAttribute('open'), false);
  assert.match(drill.textContent, /7-day mean error of the load forecasts 1\.2 kWh, inside its range 80% of the time, 7 forecasts scored/);
  assert.match(drill.textContent, /I-D7 Required signals per advisor \(retired\): OPEN/);
  assert.doesNotMatch(drill.textContent, /I-D1 /, 'recorded decisions are not listed as open');
  assert.match(drill.textContent, /Next charge target: MEDIUM/);
  assert.match(drill.textContent, /SYNTHETIC_FIXTURE/);
});

test('guards (markup): an unrecognised output shows only the one fixed notice', () => {
  const muts = [
    (a) => { a.contract_version = 'ecco-intel-entities/2'; }, (a) => { delete a.contract_version; },
    (a) => { delete a.integration_version; }, (a) => { a.integration_version = ''; }, (a) => { a.mode = 'AUTONOMOUS'; },
    (a) => { a.applies_nothing = false; }, (a) => { a.applies_nothing = 'true'; },
  ];
  for (const name of FIXTURES) {
    for (const mut of muts) {
      const { html } = renderFixture(name, { mutate: (s) => mut(s[ids.status].attributes) });
      const root = fragment(html);
      assert.equal(root.querySelector('ha-card').getAttribute('data-kind'), 'not_recognised', name);
      const notice = root.querySelectorAll('[data-callout]');
      assert.equal(notice.length, 1, name);
      assert.equal(notice[0].querySelector('h3').textContent, 'Intelligence output not recognised', name);
      assert.equal(notice[0].querySelector('p').textContent, card.NOTICE_COPY.not_recognised.body, name);
      assert.equal(figs(html).length, 0, name);
      assert.equal(root.querySelectorAll('[data-item]').length, 0, name);
      assert.equal(root.querySelector('[data-sec="banner"]'), null, `${name}: no SHADOW claim for an unrecognised output`);
      assert.equal(root.querySelector('details'), null, name);
      assert.doesNotMatch(textOf(html).replace(card.CONTRACT_VERSION, ''), /\d/, `${name}: no number at all (but the contract's name)`);
      // nothing from the output reaches the markup
      assert.doesNotMatch(html, /fixture|SYNTHETIC|DECISION_|I-D1/, name);
    }
  }
});

test('guards (markup): a prototype-shaped status is not rendered as advice', () => {
  const proto = {
    [ids.status]: {
      entity_id: ids.status, state: 'LEARNING_NORMALLY',
      attributes: { mode: 'SHADOW', applies_nothing: true, frozen_sample: true, generated_for: '2030-01-15T21:00:00+00:00', confidence: { label: 'HIGH' } },
    },
    [ids.charge_target]: { entity_id: ids.charge_target, state: '100', attributes: { mode: 'SHADOW', applies_nothing: true } },
  };
  const { html } = render(proto, nowFor('synthetic_ok'));
  assert.match(html, /Intelligence output not recognised/);
  assert.equal(figs(html).length, 0);
  assert.doesNotMatch(textOf(html), /100/);
});

test('not publishing: the banner, the fixed notice and the footer only', () => {
  for (const s of [{}, { [ids.status]: { entity_id: ids.status, state: 'unavailable', attributes: {} } }]) {
    const { html } = render(s, 0);
    const root = fragment(html);
    assert.equal(root.querySelector('ha-card').getAttribute('data-kind'), 'not_publishing');
    assert.equal(root.querySelector('[data-callout]').querySelector('h3').textContent, 'ECCO Intelligence is not publishing.');
    assert.equal(figs(html).length, 0);
    assert.equal(root.querySelector('[data-watchdog]').textContent, 'Watchdog: not installed');
  }
});

test('expired result: the expired notice and no figure', () => {
  const name = 'synthetic_ok';
  const valid = Date.parse(statesFor(name)[ids.status].attributes.valid_until);
  const { html } = render(statesFor(name), valid + 60000);
  const root = fragment(html);
  assert.equal(root.querySelector('[data-callout="expired"]').querySelector('h3').textContent, 'Result expired');
  assert.match(root.querySelector('[data-sec="quality"]').textContent, /not current/);
  assert.equal(figs(html).length, 0);
  assert.doesNotMatch(textOf(html), FIGURE_RE);
  const pill = root.querySelector('[data-pill]');
  assert.equal(pill.textContent, 'Expired', 'an expired OK result never reads "Advice ready"');
  assert.equal(pill.getAttribute('data-pill'), 'expired');
  assert.doesNotMatch(textOf(html), /Advice ready/);
});

test('withheld (markup): a result ahead of this device\'s clock, or a watchdog that reads off, shows its notice and no figure', () => {
  const cases = [
    ['clock_ahead', render(statesFor('synthetic_ok'), nowFor('synthetic_ok', -7200)).html, 'Result time is ahead of this device'],
    ['watchdog_off', renderFixture('synthetic_ok', { watchdog: 'off' }).html, 'Result not confirmed fresh'],
  ];
  for (const [kind, html, title] of cases) {
    const root = fragment(html);
    assert.equal(root.querySelector(`[data-callout="${kind}"]`).querySelector('h3').textContent, title, kind);
    assert.equal(root.querySelector(`[data-callout="${kind}"]`).querySelector('p').textContent, card.NOTICE_COPY[kind].body, kind);
    assert.equal(root.querySelector('[data-pill]').textContent, 'Not current', kind);
    assert.equal(figs(html).length, 0, kind);
    assert.doesNotMatch(textOf(html), FIGURE_RE, kind);
    assert.doesNotMatch(textOf(html), /Advice ready/, kind);
    assert.match(root.querySelector('[data-sec="quality"]').textContent, /not current/, kind);
  }
  // a small clock difference inside the PROPOSED tolerance: figures, and the age reads "just now", not "in the future"
  const near = render(statesFor('synthetic_ok'), nowFor('synthetic_ok', -60)).html;
  assert.ok(figs(near).length > 0);
  assert.match(fragment(near).querySelector('[data-age]').textContent, /, just now/);
});

test('BLOCKED / INSUFFICIENT_DATA rows: no digit at all (no condition count); the conditions are in Details', () => {
  for (const name of ['all_open_blocked', 'synthetic_ok']) {
    const root = fragment(renderFixture(name).html);
    const rows = root.querySelectorAll('[data-item]').filter((r) => ['BLOCKED', 'INSUFFICIENT_DATA'].includes(r.getAttribute('data-status')));
    if (name === 'all_open_blocked') assert.ok(rows.length >= 5, name);
    for (const r of rows) {
      assert.doesNotMatch(r.textContent, /\d/, `${name}: ${r.getAttribute('data-item')}`);
      assert.doesNotMatch(r.outerHTML || '', /data-nblock="\d/, `${name}: no count in an attribute either`);
    }
    const hinted = rows.filter((r) => r.querySelector('[data-nblock]'));
    for (const r of hinted) assert.equal(r.querySelector('[data-nblock]').textContent, '(see Details for the conditions)');
  }
  assert.doesNotMatch(renderFixture('all_open_blocked').html, /data-nblock="/, 'the marker carries no value');
});

test('self-test failed: the failed checks are listed (escaped), with no figure', () => {
  const { html } = renderFixture('self_test_failed');
  const sec = fragment(html).querySelector('[data-sec="selftest"]');
  assert.match(sec.textContent, /ENTITY_ID_MISMATCH FAIL: sensor\.ecco_intel_status registered with a suffix/);
  assert.equal(fragment(html).querySelector('[data-sec="blockers"]'), null, 'the checks are not repeated as blockers');
});

test('tariff and value (markup): a verified tariff shows its window and price; otherwise "Tariff not verified"', () => {
  const mk = (prov) => renderFixture('synthetic_ok', {
    mutate: (s) => {
      Object.assign(s[ids.status].attributes, {
        tariff: { provenance: prov, window: { start: '2030-01-16T01:00:00+00:00', end: '2030-01-16T04:30:00+00:00' }, price_range: { min: 7.5, max: 24 } },
        value: { range_gbp: [0.2, 0.45], assumptions: ['synthetic tariff', 'synthetic household'], baselines: null },
      });
    },
  }).html;
  const v = fragment(mk('VERIFIED'));
  assert.equal(v.querySelector('[data-fig="plan_precharge"]'), null, 'no plan block in this case');
  assert.equal(v.querySelector('[data-fig="tariff_window"]').textContent, '01:00 to 04:30');
  assert.equal(v.querySelector('[data-fig="tariff_price"]').textContent, '7.5 p/kWh to 24.0 p/kWh');
  assert.equal(v.querySelector('[data-fig="value"]').textContent, '£0.20 to £0.45');
  assert.deepEqual(v.querySelector('[data-sec="value"]').querySelectorAll('li').map((l) => l.textContent), ['synthetic tariff', 'synthetic household']);
  const u = fragment(mk('UNVERIFIED'));
  assert.equal(u.querySelector('[data-tariff="unverified"]').textContent, 'Tariff not verified');
  assert.equal(u.querySelector('[data-fig="tariff_window"]'), null);
  assert.equal(u.querySelector('[data-sec="value"]'), null);
  assert.doesNotMatch(textOf(mk('UNVERIFIED')), /£|p\/kWh/);
});

test('escaping: every engine string is escaped (blockers, codes, versions, input names, self-test text, assumptions)', () => {
  const evil = '<img src=x onerror=alert(1)>"\'&';
  const out = [];
  out.push(renderFixture('all_open_blocked', {
    mutate: (s) => {
      const a = s[ids.status].attributes;
      a.blockers = [{ code: evil, text: evil }];
      a.reason_codes = [evil];
      a.engine_version = evil;
      a.integration_version = evil;
      a.input_ages = [{ name: evil, age_s: 1, limit_s: 2, status: evil }];
      s[ids.charge_target].attributes.blockers = [{ code: evil, text: evil }];
      s[ids.charge_target].attributes.confidence = evil;
    },
  }).html);
  out.push(renderFixture('self_test_failed', { mutate: (s) => { s[ids.status].attributes.self_test = { [evil]: `FAIL: ${evil}` }; } }).html);
  out.push(renderFixture('synthetic_ok', {
    mutate: (s) => {
      Object.assign(s[ids.status].attributes, { tariff: { provenance: 'VERIFIED', window: evil, price_range: null },
        value: { range_gbp: [0.1, 0.2], assumptions: [evil] } });
      s[ids.charge_target].attributes.advice = { binding_constraint: evil, target_soc_pct: 80 };
      s[ids.charge_target].attributes.confidence = evil;                      // shown next to an OK charge target
      s[ids.predicted_day_load].attributes.confidence = evil;                 // shown next to an OK forecast figure
      s[ids.charge_target].attributes.reason_codes = [evil];
    },
  }).html);
  for (const html of out) {
    assert.doesNotMatch(html, /<img|onerror=alert\(1\)>|<script/i);
    assert.match(html, /&lt;img src=x onerror=alert\(1\)&gt;&quot;&#39;&amp;/);
  }
});

test('structure: no button, link, form, input, image, iframe or event-handler attribute anywhere', () => {
  for (const name of FIXTURES) {
    const { html } = renderFixture(name);
    assert.doesNotMatch(html, /<(button|a|form|input|select|textarea|img|iframe|script|object|embed)\b/i, name);
    assert.doesNotMatch(html, /\son[a-z]+=/i, name);
    assert.doesNotMatch(html, /href=|src=|url\(/i, name);
  }
});

test('details stay open across renders when asked (the element passes the open set)', () => {
  const { html } = render(statesFor('synthetic_ok'), nowFor('synthetic_ok'), { open: new Set(['drill']) });
  assert.equal(fragment(html).querySelector('details[data-k="drill"]').hasAttribute('open'), true);
});

test('pause: the footer shows the helper, and a pending pause is explained', () => {
  const on = fragment(renderFixture('synthetic_ok', { paused: 'on' }).html);
  assert.equal(on.querySelector('[data-pause]').textContent, 'Pause: on (change it with the Pause tile)');
  assert.ok(on.querySelector('[data-pausenote]'));
  const pz = fragment(renderFixture('paused', { paused: 'on' }).html);
  assert.equal(pz.querySelector('[data-pausenote]'), null);
  assert.equal(on.querySelector('[data-pausemissing]'), null);
  const missing = fragment(renderFixture('synthetic_ok', { mutate: (s) => { s[ids.status].attributes.pause_control = 'MISSING'; } }).html);
  assert.match(missing.querySelector('[data-pausemissing]').textContent, /PAUSE_CONTROL_MISSING/);
  const off = fragment(renderFixture('synthetic_ok', { watchdog: 'off' }).html);
  assert.equal(off.querySelector('[data-watchdog]').textContent, 'Watchdog: not fresh');
  const noHelper = fragment(renderFixture('synthetic_ok', { paused: null }).html);
  assert.equal(noHelper.querySelector('[data-pause]').textContent, 'Pause: not installed', 'no tile hint without the helper');
});

test('rendered text never shows undefined, null, NaN or [object Object]', () => {
  for (const name of FIXTURES) {
    assert.doesNotMatch(textOf(renderFixture(name).html), /undefined|\bnull\b|NaN|\[object/, name);
  }
});

test('the default configuration renders through renderCard with the default title', () => {
  const { html } = render(statesFor('synthetic_ok'), nowFor('synthetic_ok'), { config: cfg });
  assert.equal(fragment(html).querySelector('.title').textContent, 'ECCO Intelligence');
});

test('plan block (markup): shown with the charge target only while it is OK', () => {
  const plan = { precharge_by: '2030-01-16T04:30:00+00:00', headroom_ceiling_pct: 95, reserve_runout_at: '2030-01-16T18:10:00+00:00' };
  const ok = fragment(renderFixture('synthetic_ok', { mutate: (s) => { s[ids.status].attributes.plan = plan; } }).html);
  assert.equal(ok.querySelector('[data-fig="plan_precharge"]').textContent, '04:30');
  assert.equal(ok.querySelector('[data-fig="plan_headroom"]').textContent, '95%');
  assert.equal(ok.querySelector('[data-fig="plan_runout"]').textContent, '18:10');
  const blocked = renderFixture('all_open_blocked', { mutate: (s) => { s[ids.status].attributes.plan = plan; } }).html;
  assert.equal(fragment(blocked).querySelectorAll('[data-fig]').length, 0);
  const late = renderFixture('synthetic_ok', { afterS: 3600, mutate: (s) => { s[ids.status].attributes.plan = plan; } }).html;
  assert.equal(fragment(late).querySelectorAll('[data-fig]').length, 0, 'expired');
});

test('the header names the next refresh (next_run_at) when it is still ahead', () => {
  const root = fragment(renderFixture('synthetic_ok').html);
  assert.match(root.querySelector('[data-age]').textContent, /next refresh 21:15$/);
  const late = fragment(renderFixture('synthetic_ok', { afterS: 1200 }).html);
  assert.doesNotMatch(late.querySelector('[data-age]').textContent, /next refresh/);
});

test('codes pass through: CHARGE_WINDOW_NOT_PRICED (A41) is listed in Details like any code, nothing else changes', () => {
  const NP = 'CHARGE_WINDOW_NOT_PRICED';
  const items = ['charge_target', 'export_event', 'dump_to_grid', 'predicted_morning_soc'];
  const base = renderFixture('synthetic_ok');
  const got = renderFixture('synthetic_ok', {
    mutate: (s) => {
      for (const k of items) {
        const a = s[ids[k]].attributes;
        a.reason_codes = [...(a.reason_codes || []), 'CHARGE_WINDOW_FROM_TOU_TABLE', NP];
      }
    },
  });
  const drill = fragment(got.html).querySelector('details[data-k="drill"]');
  const lines = drill.querySelectorAll('li').map((l) => l.textContent).filter((t) => t.includes(NP));
  assert.deepEqual(lines.map((t) => t.split(':')[0]).sort(), items.map((k) => card.ITEM_LABEL[k]).sort(),
    'one Details line per charge-window item names the code');
  assert.equal(got.html.split(`<code>${NP}</code>`).length - 1, items.length, 'shown as a plain code, once per item');
  const rows = (vm) => vm.items.map((v) => [v.key, v.status, v.value, v.note, v.blockers.length]);
  assert.deepEqual(rows(got.vm), rows(base.vm), 'no item status, figure, note or blocker changes');
  assert.equal(got.vm.status, base.vm.status);
  const outsideDetails = (html) => html.replace(/<details class="drill"[\s\S]*?<\/details>/, '');
  assert.equal(outsideDetails(got.html), outsideDetails(base.html), 'outside Details the markup is unchanged');
  assert.doesNotMatch(outsideDetails(got.html), /NOT_PRICED/);
});
