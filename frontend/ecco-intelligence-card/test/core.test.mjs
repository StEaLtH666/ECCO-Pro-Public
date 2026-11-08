// Pure core: configuration, the recognition guard, the null rule in deriveModel, formatting.
import test from 'node:test';
import assert from 'node:assert/strict';
import { card, ids, statesFor, nowFor, loadFixture, FIXTURES, NULL_FIXTURES } from './helpers.mjs';

const CONTRACT_IDS = {
  status: 'sensor.ecco_intel_status', charge_target: 'sensor.ecco_intel_charge_target',
  overnight_demand: 'sensor.ecco_intel_overnight_demand', export_event: 'sensor.ecco_intel_export_event',
  dump_to_grid: 'sensor.ecco_intel_dump_to_grid', predicted_day_load: 'sensor.ecco_intel_predicted_day_load',
  pv_tomorrow: 'sensor.ecco_intel_pv_tomorrow', predicted_morning_soc: 'sensor.ecco_intel_predicted_morning_soc',
  accuracy: 'sensor.ecco_intel_accuracy', data_quality: 'sensor.ecco_intel_data_quality', fresh: 'binary_sensor.ecco_intel_fresh',
  paused: 'input_boolean.ecco_intel_paused', watchdog_fresh: 'binary_sensor.ecco_intel_watchdog_fresh',
};

test('config: the defaults are the contract entity ids, and every fixture names exactly the eleven integration ids', () => {
  assert.deepEqual({ ...card.DEFAULT_ENTITIES }, CONTRACT_IDS);
  assert.deepEqual({ ...card.validateConfig({}).entities }, CONTRACT_IDS);
  for (const name of FIXTURES) {
    const integ = Object.entries(CONTRACT_IDS).filter(([k]) => k !== 'paused' && k !== 'watchdog_fresh').map(([, v]) => v).sort();
    assert.deepEqual(Object.keys(loadFixture(name).entities).sort(), integ, name);
  }
});

test('config: overrides, unknown keys, bad ids, wrong domains, duplicates and the prototype ids are refused', () => {
  assert.equal(card.validateConfig({ entities: { status: 'sensor.site_intel_status' } }).entities.status, 'sensor.site_intel_status');
  assert.equal(card.validateConfig({ title: 'Advice' }).title, 'Advice');
  assert.throws(() => card.validateConfig(null), /invalid configuration/);
  assert.throws(() => card.validateConfig({ entities: { nope: 'sensor.x' } }), /entities\.nope is not a known entity key/);
  assert.throws(() => card.validateConfig({ entities: { status: 'Sensor.X' } }), /entities\.status must be an entity id/);
  assert.throws(() => card.validateConfig({ entities: { paused: 'switch.ecco_intel_paused' } }), /must be a input_boolean/);
  assert.throws(() => card.validateConfig({ entities: { status: 'sensor.ecco_intel_charge_target' } }), /repeats/);
  assert.throws(() => card.validateConfig({ entities: { status: 'sensor.ecco_intelligence_status' } }), /frozen V1 prototype/);
  assert.throws(() => card.validateConfig({ apply: true }), /apply is not a known option/);
  assert.throws(() => card.validateConfig({ title: 5 }), /title/);
});

test('guard: each golden fixture is recognised, with the expected kind', () => {
  const expect = { all_open_blocked: 'live', synthetic_ok: 'live', stale: 'null', paused: 'null', self_test_failed: 'null', starting: 'null' };
  for (const name of FIXTURES) {
    const vm = card.deriveModel(statesFor(name), ids, nowFor(name));
    assert.equal(vm.kind, expect[name], name);
    assert.equal(vm.status, loadFixture(name).entities[ids.status].state, name);
  }
});

const MUTATIONS = [
  ['contract_version ecco-intel-entities/2', (a) => { a.contract_version = 'ecco-intel-entities/2'; }],
  ['contract_version missing', (a) => { delete a.contract_version; }],
  ['integration_version missing', (a) => { delete a.integration_version; }],
  ['integration_version empty', (a) => { a.integration_version = ''; }],
  ['integration_version a number', (a) => { a.integration_version = 1; }],
  ['integration_version of spaces only', (a) => { a.integration_version = '   '; }],
  ['integration_version a tab and a newline', (a) => { a.integration_version = '\t\n'; }],
  ['mode ASSISTED', (a) => { a.mode = 'ASSISTED'; }],
  ['mode AUTONOMOUS', (a) => { a.mode = 'AUTONOMOUS'; }],
  ['mode missing', (a) => { delete a.mode; }],
  ['mode lower case', (a) => { a.mode = 'shadow'; }],
  ['applies_nothing false', (a) => { a.applies_nothing = false; }],
  ['applies_nothing the text true', (a) => { a.applies_nothing = 'true'; }],
  ['applies_nothing missing', (a) => { delete a.applies_nothing; }],
  ['kind not status', (a) => { a.kind = 'charge_target'; }],
  ['status attribute disagrees with the state', (a) => { a.status = a.status === 'OK' ? 'BLOCKED' : 'OK'; }],
];

test('guard: a wrong or missing contract_version / integration_version / mode / applies_nothing is not recognised', () => {
  for (const name of FIXTURES) {
    for (const [label, mut] of MUTATIONS) {
      const s = statesFor(name);
      mut(s[ids.status].attributes);
      const vm = card.deriveModel(s, ids, nowFor(name));
      assert.equal(vm.kind, 'not_recognised', `${name}: ${label}`);
      assert.equal(vm.items, undefined, `${name}: ${label}: no item is derived`);
    }
  }
});

test('guard: an unknown status word, or a prototype-shaped status (no contract_version), is not recognised', () => {
  const s = statesFor('synthetic_ok');
  s[ids.status].state = 'LEARNING_NORMALLY';
  s[ids.status].attributes.status = 'LEARNING_NORMALLY';
  assert.equal(card.deriveModel(s, ids, nowFor('synthetic_ok')).kind, 'not_recognised');
  // the frozen V1 prototype's status shape: SHADOW, applies_nothing, but no contract_version / integration_version
  const proto = {
    [ids.status]: {
      entity_id: ids.status, state: 'LEARNING_NORMALLY',
      attributes: { mode: 'SHADOW', applies_nothing: true, frozen_sample: true, generated_for: '2030-01-15T21:00:00+00:00', model_version: 'intel-v1.0.0-shadow' },
    },
  };
  assert.equal(card.deriveModel(proto, ids, nowFor('synthetic_ok')).kind, 'not_recognised');
});

test('guard: a missing, unknown or unavailable status entity is not publishing', () => {
  assert.equal(card.deriveModel({}, ids, 0).kind, 'not_publishing');
  for (const st of ['unknown', 'unavailable']) {
    const s = statesFor('synthetic_ok');
    s[ids.status].state = st;
    assert.equal(card.deriveModel(s, ids, nowFor('synthetic_ok')).kind, 'not_publishing', st);
  }
});

test('null rule: no item value, band or advice under STALE / PAUSED / SELF_TEST_FAILED / STARTING', () => {
  for (const name of NULL_FIXTURES) {
    const vm = card.deriveModel(statesFor(name), ids, nowFor(name));
    assert.equal(vm.numbersAllowed, false, name);
    for (const v of vm.items) {
      assert.equal(v.value, null, `${name}.${v.key}`);
      assert.equal(v.band, null, `${name}.${v.key}`);
      assert.equal(v.advice, null, `${name}.${v.key}`);
    }
    assert.equal(vm.tariff, undefined, name);
    assert.equal(vm.value, undefined, name);
    assert.equal(vm.accuracy, undefined, name);
  }
});

test('null rule: even a forged numeric item state under a null-rule status gives no value', () => {
  const s = statesFor('stale');
  for (const k of [...card.ADVICE_ITEMS, ...card.FORECAST_ITEMS]) {
    s[ids[k]].state = '42.0';
    s[ids[k]].attributes.status = 'OK';
    s[ids[k]].attributes.valid_until = '2031-01-01T00:00:00+00:00';
    s[ids[k]].attributes.generated_at = s[ids.status].attributes.generated_at;
  }
  const vm = card.deriveModel(s, ids, nowFor('stale'));
  assert.ok(vm.items.every((v) => v.value === null));
});

test('null rule: no value for a BLOCKED / INSUFFICIENT_DATA / NO_ADVICE item, even with a forged numeric state', () => {
  for (const name of ['all_open_blocked', 'synthetic_ok']) {
    const s = statesFor(name);
    for (const k of [...card.ADVICE_ITEMS, ...card.FORECAST_ITEMS]) {
      if (s[ids[k]].attributes.status !== 'OK') {
        s[ids[k]].state = '55.0';
        s[ids[k]].attributes.p10 = 1;
        s[ids[k]].attributes.p90 = 2;
      }
    }
    const vm = card.deriveModel(s, ids, nowFor(name));
    for (const v of vm.items) {
      if (v.status !== 'OK') assert.equal(v.value, null, `${name}.${v.key}`);
    }
  }
  const all = card.deriveModel(statesFor('all_open_blocked'), ids, nowFor('all_open_blocked'));
  assert.ok(all.items.every((v) => v.value === null), 'all-OPEN: no value anywhere');
});

test('synthetic_ok: the OK items carry their published values and bands', () => {
  const vm = card.deriveModel(statesFor('synthetic_ok'), ids, nowFor('synthetic_ok'));
  const by = Object.fromEntries(vm.items.map((v) => [v.key, v]));
  assert.equal(by.charge_target.value, 80);
  assert.equal(by.overnight_demand.value, 6.4);
  assert.equal(by.predicted_day_load.value, 14.2);
  assert.deepEqual(by.predicted_day_load.band, [11, 17.5]);
  assert.equal(by.pv_tomorrow.value, 9.8);
  assert.deepEqual(by.pv_tomorrow.band, [6.1, 12.4]);
  assert.equal(by.predicted_morning_soc.value, 72);
  assert.equal(by.predicted_morning_soc.band, null);
  assert.equal(by.export_event.value, null);
  assert.equal(by.dump_to_grid.value, null);
  assert.deepEqual(vm.accuracy, { mae: 1.2, coverage: 0.8, n: 7 });
  assert.equal(vm.dataQuality, 'OK');
});

test('per-item guards: wrong item contract, another cycle, an expired item or a non-numeric state give no value', () => {
  const name = 'synthetic_ok';
  const cases = [
    ['item contract_version', (s) => { s[ids.charge_target].attributes.contract_version = 'x'; }, 'Not available'],
    ['item mode', (s) => { s[ids.charge_target].attributes.mode = 'ASSISTED'; }, 'Not available'],
    ['item kind', (s) => { s[ids.charge_target].attributes.kind = 'dump_to_grid'; }, 'Not available'],
    ['another cycle', (s) => { s[ids.charge_target].attributes.generated_at = '2030-01-15T20:45:00+00:00'; }, 'Updating'],
    ['item expired', (s) => { s[ids.charge_target].attributes.valid_until = '2030-01-15T21:01:00+00:00'; }, 'Not available'],
    ['item without validity', (s) => { s[ids.charge_target].attributes.valid_until = null; }, 'Not available'],
    ['state unknown', (s) => { s[ids.charge_target].state = 'unknown'; }, 'Not available'],
    ['state text', (s) => { s[ids.charge_target].state = '80%'; }, 'Not available'],
    ['entity missing', (s) => { delete s[ids.charge_target]; }, 'Not available'],
  ];
  for (const [label, mut, note] of cases) {
    const s = statesFor(name);
    mut(s);
    const vm = card.deriveModel(s, ids, nowFor(name));
    const ct = vm.items.find((v) => v.key === 'charge_target');
    assert.equal(ct.value, null, label);
    assert.equal(ct.note, note, label);
  }
});

test('card-side expiry: past the status valid_until nothing has a value', () => {
  const name = 'synthetic_ok';
  const valid = Date.parse(loadFixture(name).entities[ids.status].recorded.valid_until);
  const at = card.deriveModel(statesFor(name), ids, valid);
  assert.equal(at.expired, false);
  assert.ok(at.items.some((v) => v.value !== null));
  const after = card.deriveModel(statesFor(name), ids, valid + 1000);
  assert.equal(after.expired, true);
  assert.ok(after.items.every((v) => v.value === null));
  assert.equal(after.value, null);
  assert.equal(after.plan, null);
});

test('withheld: a result timed more than the PROPOSED 120 s ahead of the card\'s clock shows no figure (clock_ahead)', () => {
  const name = 'synthetic_ok';
  for (const [afterS, allowed] of [[0, true], [-60, true], [-120, true], [-121, false], [-7200, false]]) {
    const vm = card.deriveModel(statesFor(name), ids, nowFor(name, afterS));
    assert.equal(vm.numbersAllowed, allowed, `card clock ${afterS} s from generated_at`);
    assert.equal(vm.withheld, allowed ? '' : 'clock_ahead', `card clock ${afterS} s`);
    if (!allowed) {
      assert.ok(vm.items.every((v) => v.value === null), `${afterS}: no item value`);
      assert.equal(vm.accuracy, null);
      assert.equal(vm.value, null);
      assert.equal(vm.plan, null);
      assert.deepEqual(vm.inputAges, []);
    }
  }
  assert.equal(card.CLOCK_AHEAD_MS, 120000, 'PROPOSED, the same as the package watchdog CLOCK_AHEAD_S');
});

test('withheld: a watchdog that reads off withholds every figure; missing or unknown leaves the card\'s own checks', () => {
  const name = 'synthetic_ok';
  const off = card.deriveModel(statesFor(name, { watchdog: 'off' }), ids, nowFor(name));
  assert.equal(off.withheld, 'watchdog_off');
  assert.equal(off.numbersAllowed, false);
  assert.ok(off.items.every((v) => v.value === null));
  assert.equal(off.accuracy, null);
  for (const [label, opts] of [['missing', { watchdog: null }], ['unknown', { watchdog: 'unavailable' }], ['on', {}]]) {
    const vm = card.deriveModel(statesFor(name, opts), ids, nowFor(name));
    assert.equal(vm.withheld, '', label);
    assert.ok(vm.items.some((v) => v.value !== null), label);
  }
  // expiry is reported first (the card's clock), then the clock check, then the watchdog
  const valid = Date.parse(loadFixture(name).entities[ids.status].recorded.valid_until);
  assert.equal(card.deriveModel(statesFor(name, { watchdog: 'off' }), ids, valid + 1000).withheld, 'expired');
  for (const n of NULL_FIXTURES) assert.equal(card.deriveModel(statesFor(n, { watchdog: 'off' }), ids, nowFor(n)).withheld, '', n);
});

test('the accuracy and data-quality entities count only when they belong to the same publish as the status', () => {
  const name = 'synthetic_ok';
  const s = statesFor(name);
  s[ids.accuracy].attributes.generated_at = '2030-01-14T21:00:00+00:00';
  s[ids.data_quality].attributes.generated_at = '2030-01-14T21:00:00+00:00';
  s[ids.data_quality].state = 'DEGRADED';
  const vm = card.deriveModel(s, ids, nowFor(name));
  assert.equal(vm.accuracy, null, 'the previous cycle\'s accuracy is not shown next to the current result');
  assert.equal(vm.dataQuality, 'OK', 'the status\'s own data_quality, not the other cycle\'s entity');
  const same = statesFor(name);
  same[ids.data_quality].state = 'DEGRADED';
  assert.equal(card.deriveModel(same, ids, nowFor(name)).dataQuality, 'DEGRADED', 'the same publish: the entity is used');
  const noGen = statesFor(name);
  delete noGen[ids.accuracy].attributes.generated_at;
  assert.equal(card.deriveModel(noGen, ids, nowFor(name)).accuracy, null, 'no generated_at: not tied to this cycle');
});

test('tariff, value and plan blocks: only with a VERIFIED tariff and an OK charge target', () => {
  const name = 'synthetic_ok';
  const at = nowFor(name);
  const withBlocks = (prov, value, plan) => {
    const s = statesFor(name);
    const a = s[ids.status].attributes;
    a.tariff = { provenance: prov, window: { start: '2030-01-16T01:00:00+00:00', end: '2030-01-16T04:30:00+00:00' }, price_range: [7.5, 24.0] };
    a.value = value;
    a.plan = plan;
    return card.deriveModel(s, ids, at);
  };
  const v = withBlocks('VERIFIED', { range_gbp: [0.2, 0.45], assumptions: ['synthetic'], baselines: null }, { precharge_by: '2030-01-16T04:30:00+00:00' });
  assert.equal(v.tariff.verified, true);
  assert.deepEqual(v.tariff.window, [Date.parse('2030-01-16T01:00:00+00:00'), Date.parse('2030-01-16T04:30:00+00:00')]);
  assert.deepEqual(v.tariff.price, [7.5, 24]);
  assert.deepEqual(v.value, { range: [0.2, 0.45], assumptions: ['synthetic'] });
  assert.equal(v.plan.precharge, Date.parse('2030-01-16T04:30:00+00:00'));
  assert.equal(withBlocks('VERIFIED_FROM_INTEGRATION', null, null).tariff.verified, true);
  for (const prov of ['UNVERIFIED', 'verified', null, 'CALLER_DECLARATION_UNVERIFIED']) {
    const u = withBlocks(prov, { range_gbp: [0.2, 0.45], assumptions: ['x'] }, null);
    assert.equal(u.tariff.verified, false, String(prov));
    assert.equal(u.tariff.window, null, String(prov));
    assert.equal(u.tariff.price, null, String(prov));
    assert.equal(u.value, null, String(prov));
  }
  assert.equal(withBlocks('VERIFIED', { range_gbp: [0.2, 0.45], assumptions: [] }, null).value, null, 'no assumptions');
  assert.equal(withBlocks('VERIFIED', { range_gbp: [0.5, 0.2], assumptions: ['x'] }, null).value, null, 'inverted range');
  assert.equal(withBlocks('VERIFIED', { range_gbp: ['0.2', '0.5'], assumptions: ['x'] }, null).value, null, 'text range');
  const s = statesFor('all_open_blocked');
  s[ids.status].attributes.tariff = { provenance: 'VERIFIED', window: null, price_range: [1, 2] };
  s[ids.status].attributes.value = { range_gbp: [0.2, 0.45], assumptions: ['x'] };
  const b = card.deriveModel(s, ids, nowFor('all_open_blocked'));
  assert.equal(b.value, null, 'no value block without an OK charge target');
  assert.equal(b.plan, null);
});

test('decisions: every I-D label in order, with its title and status', () => {
  const vm = card.deriveModel(statesFor('all_open_blocked'), ids, nowFor('all_open_blocked'));
  assert.deepEqual(vm.decisions.map((d) => d.label), ['I-D1', 'I-D2', 'I-D3', 'I-D4', 'I-D5', 'I-D6', 'I-D7', 'I-D8', 'I-D9']);
  assert.ok(vm.decisions.every((d) => d.status === 'OPEN' && d.title.length > 0));
  const ok = card.deriveModel(statesFor('synthetic_ok'), ids, nowFor('synthetic_ok'));
  assert.deepEqual(ok.decisions.filter((d) => d.status !== 'RECORDED').map((d) => d.label), ['I-D7']);
});

test('last_good: carried only under a null-rule status, with its time', () => {
  const st = card.deriveModel(statesFor('stale'), ids, nowFor('stale'));
  assert.equal(st.lastGood.genMs, Date.parse('2030-01-15T21:00:00+00:00'));
  assert.deepEqual(st.lastGood.rows.map((r) => [r.key, r.value]), [
    ['charge_target', 80], ['overnight_demand', 6.4], ['predicted_day_load', 14.2], ['pv_tomorrow', 9.8], ['predicted_morning_soc', 72],
  ]);
  const ok = card.deriveModel(statesFor('synthetic_ok'), ids, nowFor('synthetic_ok'));
  assert.equal(ok.lastGood, undefined);
});

test('formatting: rounding rules and the report age', () => {
  assert.equal(card.figure(79.6, '%'), '80%');
  assert.equal(card.figure(6.44, 'kWh'), '6.4 kWh');
  assert.equal(card.figure(21.4, 'kWh'), '21 kWh');
  assert.equal(card.figure(0.2, 'GBP'), '£0.20');
  const f = card.makeFormatters({ locale: 'en-GB', timeZone: 'Europe/London' });
  assert.equal(f.age(30 * 1000), 'just now');
  assert.equal(f.age(2 * 60000), '2 min ago');
  assert.equal(f.age(65 * 60000), '1 h 5 min ago');
  assert.equal(f.age(-60000), 'just now', 'a small clock difference');
  assert.equal(f.age(-120000), 'just now', 'at the PROPOSED tolerance');
  assert.equal(f.age(-121000), 'in the future');
  assert.equal(f.time(Date.parse('2030-01-15T21:00:00+00:00')), '21:00');
  assert.equal(f.time(Date.parse('2030-07-15T21:00:00+00:00')), '22:00', 'BST');
});

test('parsing: finite and parseTime refuse what is not plainly a number / an aware ISO time', () => {
  assert.equal(card.finite('80.0'), 80);
  assert.equal(card.finite(' 6.4 '), 6.4);
  for (const v of ['', 'NaN', 'Infinity', '80%', 'unknown', null, true, NaN, Infinity, {}, []]) assert.equal(card.finite(v), null, String(v));
  assert.equal(card.parseTime('2030-01-15T21:00:00+00:00'), Date.parse('2030-01-15T21:00:00+00:00'));
  for (const v of ['2030-01-15T21:00:00', '21:00', 'soon', 1894741200, null]) assert.equal(card.parseTime(v), null, String(v));
});

test('fuzz: 600 seeded corruptions of the fixtures never throw, and a figure only ever comes from an OK item of a live result', () => {
  let seed = 20301015;
  const rnd = () => { seed = (seed * 1103515245 + 12345) % 2147483648; return seed / 2147483648; };
  const pick = (a) => a[Math.floor(rnd() * a.length)];
  const junk = [null, undefined, '', 'x', 0, -1, 1e308, NaN, true, false, [], {}, [1, 2], { code: 1 }, '2030-01-15T21:10:00+00:00', '80.0', 'OK',
    'SHADOW', 'ecco-intel-entities/1'];
  const keys = ['contract_version', 'mode', 'applies_nothing', 'integration_version', 'kind', 'status', 'generated_at', 'valid_until',
    'blockers', 'reason_codes', 'decisions', 'tariff', 'value', 'plan', 'input_ages', 'last_good', 'self_test', 'confidence', 'advice', 'p10', 'p90'];
  for (let i = 0; i < 600; i += 1) {
    const name = pick(FIXTURES);
    const s = statesFor(name);
    const eids = Object.keys(s);
    for (let j = 0; j < 1 + Math.floor(rnd() * 4); j += 1) {
      const st = s[pick(eids)];
      const r = rnd();
      if (r < 0.15) st.state = pick(['unknown', 'unavailable', '42.0', '', 'OK', 'STALE', 'BLOCKED']);
      else if (r < 0.25) st.attributes = pick([null, undefined, [], 'x']);
      else if (st.attributes && typeof st.attributes === 'object') st.attributes[pick(keys)] = pick(junk);
    }
    const now = nowFor(name, pick([0, 120, 1800, 3600, -60]));
    let vm;
    let html;
    assert.doesNotThrow(() => { vm = card.deriveModel(s, ids, now); html = card.renderCard(vm, card.validateConfig({}), undefined, new Set()); }, `case ${i}`);
    const figs = [...html.matchAll(/data-fig="([a-z_]+)"/g)].map((m) => m[1]);
    if (vm.kind !== 'live') assert.deepEqual(figs, [], `case ${i}: ${vm.kind}`);
    for (const k of figs.filter((f) => ids[f])) {
      const st = s[ids[k]];
      assert.equal(st.attributes.status, 'OK', `case ${i}: ${k}`);
      assert.ok(card.finite(st.state) !== null, `case ${i}: ${k}`);
      assert.ok(Date.parse(st.attributes.valid_until) >= now, `case ${i}: ${k}`);
    }
    assert.doesNotMatch(html, /undefined|NaN|\[object/, `case ${i}`);
  }
});
