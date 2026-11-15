// Review round 8 ([r8]): the BUDGET class of the redactor, three findings of the eighth review.
//
//  (1) KEY UNREAD (reviewer mutant M14). A key that the entity budget could not pay for is not read, and the card withholds ITS VALUE, whatever the value is. The round-7 tests only had strings under such keys, so a
//      card that showed every number and every boolean under an unread key (KEY_UNREAD with secret: false) passed all of them; a number under `password`, `pin_code` or `latitude` was shown.
//  (2) CHARGE ORDER (reviewer probe 8b). The state, the name and the unit are what a row shows first, so they are charged and read first; an entity that is over its budget still shows them, honestly, and it is the
//      attributes that are withheld.
//  (3) THE SNAPSHOT BUDGET. The entity budget bounds one entity and nothing bounded the total (5000 entities of near-miss text took 112 s to read for the first render). A snapshot now reads at most LIMITS.snapshotChars
//      characters across ALL its entities, in a documented order (alert-bearing first, then headline sources, then the other sources, then the discovered entities by id); past it the remaining entities are NOT READ: their
//      rows say so, their values are withheld, nothing of them is scanned, shown, searched or exported, and the alerts (which read the raw states) are never affected. The timing of it is in perf.test.mjs.
import test from 'node:test';
import assert from 'node:assert/strict';
import { loadCard, miniCatalogue, miniStates, mkState, NOW } from './helpers.mjs';
import { filler } from './secrets.mjs';

const core = await loadCard('budget8');
const { WITHHELD, LIMITS, UNREAD_KEY, buildSnapshot, validateCatalogue, deriveAlerts, summarise, searchRows, exportRows, redactAttributes, redactValue, countWithheld } = core;

const snap = (mutate = null, catalogue = miniCatalogue()) => buildSnapshot(miniStates(mutate), validateCatalogue(catalogue).catalogue, NOW);
const byEntity = (s, eid) => s.rows.find((r) => r.entity_id === eid);
const j = (...p) => p.join('');
const ELLIPSIS = String.fromCharCode(0x2026);
const everything = (rows) => JSON.stringify(rows.map((r) => [r.stateText, r.unitText, r.title, r.attributes, r.redacted, r.searchText, r.entity_id]));

// ===========================================================================================================================
// (1) a key the budget could not pay for
// ===========================================================================================================================
// six harmless texts of 19990 characters use up the entity budget (100000); everything after them is under a key that was NOT read
const spentBudget = () => {
  const a = {};
  for (let i = 0; i < 6; i += 1) a[`filler_${i}`] = filler(19990);
  return a;
};
const UNREAD_KEYS = {
  pin_code: 7349213, password: 6502719, latitude: 51.50722, wifi_pass: true, secret_list: [4242421, 4242422], nested: { inner_marker: 'zq8nestedvalue', amount: 8383831 },
  harmless_count: 7, harmless_flag: false, harmless_list: [9191911, 9191912], harmless_dict: { deep: { deeper: 'zq8deepvalue', n: 7373731 } },
};
const NUMBER_PROBES = ['7349213', '6502719', '51.50722', '4242421', '4242422', 'zq8nestedvalue', '8383831', '9191911', '9191912', 'zq8deepvalue', '7373731'];

test('AC10 [r8] KEY UNREAD (reviewer mutant M14): after the budget is gone, a number, a boolean, a list and a nested dict under a key the card has not read (password, pin_code, latitude, wifi_pass, and any other name) are withheld, whatever they are', () => {
  const attrs = { ...spentBudget(), ...UNREAD_KEYS };
  const out = redactAttributes(attrs);
  const entries = Object.entries(out);
  assert.equal(entries.length, 6 + Object.keys(UNREAD_KEYS).length);
  assert.ok(entries.slice(6).every(([k, v]) => k.startsWith('[withheld key') && v === WITHHELD), 'every entry after the budget is an unread key with a withheld value (a number and a boolean too, and a list, and a dict)');
  assert.equal(countWithheld(out) >= 2 * Object.keys(UNREAD_KEYS).length, true);
  const text = JSON.stringify(out);
  for (const p of NUMBER_PROBES) assert.ok(!text.includes(p), `the raw attributes carry ${p}`);
  // the same under a list at the top (the export's shape) and under a dict one level down
  const nested = redactValue({ inner: attrs });
  for (const p of NUMBER_PROBES) assert.ok(!JSON.stringify(nested).includes(p), `a nested dict carries ${p}`);
});

test('AC10 [r8] KEY UNREAD, every path: the row, the attribute rows, the raw view, the search index, a search, the JSON export and the CSV export carry nothing that sat under an unread key', () => {
  const s = snap((states) => { states['sensor.ecco_intel_unread_keys'] = mkState('sensor.ecco_intel_unread_keys', 'ok', { ...spentBudget(), ...UNREAD_KEYS }); });
  const r = byEntity(s, 'sensor.ecco_intel_unread_keys');
  assert.ok(r && !r.unread, 'the entity was read: it is its own budget that ran out');
  assert.ok(r.attributes.some((a) => a.name.includes('values not read')), 'and it says so');
  const tail = Object.entries(r.redacted).slice(6);
  assert.equal(tail.length, Object.keys(UNREAD_KEYS).length);
  assert.ok(tail.every(([, v]) => v === WITHHELD));
  const rowsText = everything(s.rows);
  for (const p of NUMBER_PROBES) {
    assert.ok(!rowsText.includes(p), `a row carries ${p}`);
    assert.equal(searchRows(s.rows, p).length, 0, `a search for ${p} finds a row`);
  }
  const exported = exportRows(s.rows, 'json', { nowMs: NOW }) + exportRows(s.rows, 'csv', { nowMs: NOW });
  for (const p of NUMBER_PROBES) assert.ok(!exported.includes(p), `an export carries ${p}`);
  // the attribute rows: every row of an unread key says withheld, and none shows a number or a boolean
  const attrRows = r.attributes.filter((a) => a.name.startsWith('[withheld key'));
  assert.ok(attrRows.length >= Object.keys(UNREAD_KEYS).length);
  assert.ok(attrRows.every((a) => a.withheld === true), 'each attribute row of an unread key is withheld');
});

test('AC10 [r8] KEY UNREAD, the controls: the same keys with the budget NOT used up are withheld by their NAMES (the secret ones) or shown whole (the harmless ones), so the withholding after the budget is the budget\'s and not the names\'', () => {
  const out = redactAttributes({ ...UNREAD_KEYS });
  assert.equal(out.pin_code, WITHHELD);
  assert.equal(out.password, WITHHELD);
  assert.equal(out.latitude, WITHHELD);
  assert.equal(out.wifi_pass, WITHHELD);
  assert.equal(out.secret_list, WITHHELD);
  assert.equal(out.harmless_count, 7);
  assert.equal(out.harmless_flag, false);
  assert.deepEqual(out.harmless_list, [9191911, 9191912]);
  assert.equal(out.harmless_dict.deep.deeper, 'zq8deepvalue');
  // and a number under an unread key whose name is perfectly harmless is withheld too (the card does not guess from a name it has not read)
  const after = redactAttributes({ ...spentBudget(), harmless_count: 7 });
  assert.equal(Object.values(after)[6], WITHHELD);
});

// ===========================================================================================================================
// (2) charge order
// ===========================================================================================================================
test('AC12 [r8] CHARGE ORDER (reviewer probe 8b): an entity over its budget still shows its state, its name and its unit; the attributes past the budget are the part that is withheld', () => {
  const attrs = { friendly_name: 'Intel status', unit_of_measurement: 'kW' };
  for (let i = 0; i < 6; i += 1) attrs[`log${i}`] = filler(19990);
  const s = snap((states) => { states['sensor.ecco_intel_charge_order'] = mkState('sensor.ecco_intel_charge_order', 'healthy', attrs); });
  const r = byEntity(s, 'sensor.ecco_intel_charge_order');
  assert.equal(r.status, 'LIVE');
  assert.equal(r.stateText, 'healthy', 'the state is read first and shown');
  assert.equal(r.unitText, 'kW', 'and the unit');
  assert.equal(r.title, 'Intel status', 'and the name');
  assert.equal(r.redacted.log0, `${filler(19990).slice(0, 4000)}${ELLIPSIS} [truncated 15990 more characters]`);
  const last = Object.entries(r.redacted).at(-1);
  assert.ok(last[0].startsWith('[withheld key') && last[1] === WITHHELD, 'the last attribute, past the budget, is an unread key with a withheld value');
  assert.ok(Object.values(r.redacted).filter((v) => v === WITHHELD).length >= 2, 'the attributes past the budget are withheld');
  assert.ok(r.attributes.some((a) => a.name.includes('values not read')));
  assert.equal(r.unread, false, 'it is its own budget that ran out, not the snapshot\'s');
});

test('AC12 [r8] CHARGE ORDER: the name and the unit that look secret are withheld although they are read first; the state of an entity within its budget is as before', () => {
  const attrs = { friendly_name: j('gh', 'p_', 'A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8'), unit_of_measurement: j('postgres', 'ql', ':', '//', 'db.example', '.test/ecco') };
  const s = snap((states) => { states['sensor.ecco_intel_charge_secret'] = mkState('sensor.ecco_intel_charge_secret', j('gh', 'p_', 'A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8'), attrs); });
  const r = byEntity(s, 'sensor.ecco_intel_charge_secret');
  assert.equal(r.stateText, WITHHELD);
  assert.equal(r.unitText, '');
  assert.equal(r.title, 'sensor.ecco_intel_charge_secret', 'the name that looks secret is not the title');
  const ok = snap((states) => { states['sensor.ecco_intel_charge_ok'] = mkState('sensor.ecco_intel_charge_ok', '42', { friendly_name: 'Plain name', unit_of_measurement: 'kWh', note: 'a short note' }); });
  const o = byEntity(ok, 'sensor.ecco_intel_charge_ok');
  assert.equal(o.stateText, '42');
  assert.equal(o.unitText, 'kWh');
  assert.equal(o.title, 'Plain name');
  assert.equal(o.redacted.note, 'a short note');
});

// ===========================================================================================================================
// (3) the snapshot budget
// ===========================================================================================================================
const bigCatalogue = (n, { alerts = [], headline = [] } = {}) => {
  const sources = Array.from({ length: n }, (_, i) => ({
    id: `B${String(i).padStart(2, '0')}`, entity_id: `sensor.ecco_big_${String(i).padStart(2, '0')}`, group: 'g', title: `Big ${i}`, description: '', priority: headline.includes(i) ? 'headline' : 'normal', unit: null,
    expected_update_s: null, stale_after_s: null, origin: 'integration', attributes: [],
  }));
  const v = validateCatalogue({
    schema: 'ecco-geek-catalogue/1', view_id: 'big', title: 'Big', contract: 'big/1', groups: [{ id: 'g', title: 'G', order: 1, description: '' }], sources,
    discover: { entity_prefixes: [], group: 'g', exclude_entity_ids: [] },
    alerts: alerts.map((i) => ({ id: `AL${i}`, severity: 'critical', entity_id: `sensor.ecco_big_${String(i).padStart(2, '0')}`, when: { state_in: ['bad'] }, text: `Entity ${i} is bad.`, action: 'Look at it.' })),
    exceptions: [], redaction: { extra_key_patterns: [] },
  });
  assert.equal(v.ok, true, JSON.stringify(v.errors));
  return v.catalogue;
};
const bigAttrs = (marker) => {
  const a = {};
  for (let i = 0; i < 6; i += 1) a[`text_${i}`] = `${marker}${i} ${filler(19970)}`;
  return a;
};
const bigStates = (n, { bad = [] } = {}) => {
  const out = {};
  for (let i = 0; i < n; i += 1) {
    const id = `sensor.ecco_big_${String(i).padStart(2, '0')}`;
    out[id] = mkState(id, bad.includes(i) ? 'bad' : 'ok', bigAttrs(`zqmark${String(i).padStart(2, '0')}x`));
  }
  return out;
};

test('AC12 [r8] the snapshot budget: LIMITS.snapshotChars is 2000000, twenty of the largest entities the entity budget allows, and the cost of a value and of an entity are small whole numbers', () => {
  assert.equal(LIMITS.snapshotChars, 2000000);
  assert.equal(LIMITS.snapshotChars / LIMITS.entityChars, 20);
  assert.equal(LIMITS.nodeChars, 1);
  assert.equal(LIMITS.entityBaseChars, 250);
  assert.equal(LIMITS.entityIdChars, 255);
  assert.ok(LIMITS.snapshotChars >= 10 * LIMITS.entityChars && LIMITS.snapshotChars <= 100 * LIMITS.entityChars, 'a bound on the first render, not a licence');
  assert.ok(Object.isFrozen(LIMITS));
});

test('AC12 [r8] THE ORDER: alert-bearing entities are charged first, then the headline sources, then the other sources in catalogue order, and once the budget is used up every entity that follows is NOT READ', () => {
  const N = 30;
  const cat = bigCatalogue(N, { alerts: [29], headline: [28] });
  const s = buildSnapshot(bigStates(N), cat, NOW);
  const id = (i) => `sensor.ecco_big_${String(i).padStart(2, '0')}`;
  const order = [29, 28, ...Array.from({ length: 28 }, (_, i) => i)];
  const cost = s.rows.find((r) => !r.unread).spent;
  assert.ok(cost >= LIMITS.entityChars && cost < LIMITS.entityChars + 1000, `an entity of this size costs ${cost}`);
  let left = LIMITS.snapshotChars;
  const expectRead = new Map();
  for (const i of order) {
    expectRead.set(i, left > 0);
    if (left > 0) left -= cost;
  }
  for (const i of order) assert.equal(!byEntity(s, id(i)).unread, expectRead.get(i), `${id(i)} (position ${order.indexOf(i)}) is ${expectRead.get(i) ? 'read' : 'not read'}`);
  const read = order.filter((i) => expectRead.get(i));
  assert.ok(read.length >= 19 && read.length <= 20, `${read.length} entities are read`);
  assert.ok(read.includes(29) && read.includes(28) && read.includes(0), 'the alert-bearing entity, the headline one and the first of the others are read');
  assert.ok(!read.includes(27) && !read.includes(26), 'and the last of the others are not');
  assert.equal(s.counts.unread, N - read.length);
  assert.equal(s.rows.filter((r) => r.unread).length, s.counts.unread);
  // a catalogue that is not in this order (the alert-bearing entity LAST in the catalogue) is still read first
  assert.equal(byEntity(s, id(29)).unread, false);
});

test('AC12 [r8] an entity that was not read says so and carries NOTHING of itself: no state, no attribute, no name, no marker text, in the row, the attribute list, the raw view, the search index, a search and both exports', () => {
  const N = 30;
  const s = buildSnapshot(bigStates(N), bigCatalogue(N), NOW);
  const unread = s.rows.filter((r) => r.unread);
  assert.ok(unread.length >= 8, `${unread.length} entities not read`);
  for (const r of unread) {
    assert.equal(r.stateText, WITHHELD);
    assert.equal(r.unitText, '');
    assert.equal(r.problem, true, 'it is a problem row (the Problems filter lists it)');
    assert.equal(r.attributes.length, 1);
    assert.ok(r.attributes[0].name.includes('values not read') && r.attributes[0].value.includes('not read'));
    assert.deepEqual(Object.keys(r.redacted), [UNREAD_KEY]);
    assert.ok(r.searchText.includes('not read'));
    assert.ok(r.withheld >= 1, 'the withheld value is counted');
    assert.ok(r.attributes[0].declared === false);
    assert.equal(r.spent, 0);
  }
  const text = everything(unread);
  const exported = exportRows(unread, 'json', { nowMs: NOW }) + exportRows(unread, 'csv', { nowMs: NOW });
  for (let i = 0; i < N; i += 1) {
    const marker = `zqmark${String(i).padStart(2, '0')}x`;
    const row = byEntity(s, `sensor.ecco_big_${String(i).padStart(2, '0')}`);
    if (row.unread) {
      assert.ok(!text.includes(marker), `${marker} is in a row that was not read`);
      assert.ok(!exported.includes(marker), `${marker} is in an export of a row that was not read`);
      assert.equal(searchRows(s.rows, marker).length, 0, `a search for ${marker} finds nothing`);
    } else {
      assert.ok(JSON.stringify(row.redacted).includes(marker), `${marker}: a row that was read shows its text`);
    }
  }
  assert.ok(searchRows(s.rows, 'not read').length >= unread.length, 'the rows that were not read can be found by saying so');
  // the honest status survives: an entity that was not read is still classified from its timestamp (live here), and its state `unavailable` is still said
  const states = bigStates(N);
  states['sensor.ecco_big_27'] = mkState('sensor.ecco_big_27', 'unavailable', bigAttrs('zqmark27x'));
  const t = buildSnapshot(states, bigCatalogue(N), NOW);
  const r27 = byEntity(t, 'sensor.ecco_big_27');
  assert.equal(r27.unread, true);
  assert.equal(r27.status, 'UNAVAILABLE');
  assert.equal(r27.stateText, 'Unavailable', 'the word unavailable is the card\'s own, not the entity\'s');
  assert.ok(!everything([r27]).includes('zqmark27x'));
});

test('AC12 [r8] ALERTS ARE NEVER HIDDEN BY THE BUDGET: thirty alert-bearing entities in a state that raises an alert, half of them not read, and all thirty alerts are derived (the alerts read the raw states)', () => {
  const N = 30;
  const all = Array.from({ length: N }, (_, i) => i);
  const cat = bigCatalogue(N, { alerts: all });
  const bad = buildSnapshot(bigStates(N, { bad: all }), cat, NOW);
  assert.ok(bad.counts.unread >= 8, 'the budget is used up');
  const alerts = deriveAlerts(bad, cat);
  assert.equal(alerts.filter((a) => a.kind === 'condition').length, N, 'every alert is derived');
  assert.deepEqual([...new Set(alerts.map((a) => a.severity))], ['critical']);
  assert.deepEqual(alerts.map((a) => a.id).sort(), all.map((i) => `AL${i}`).sort());
  // the same states with every entity small (so that nothing is unread) give the same alerts
  const small = {};
  for (let i = 0; i < N; i += 1) small[`sensor.ecco_big_${String(i).padStart(2, '0')}`] = mkState(`sensor.ecco_big_${String(i).padStart(2, '0')}`, 'bad', {});
  const ref = buildSnapshot(small, cat, NOW);
  assert.equal(ref.counts.unread, 0);
  assert.deepEqual(deriveAlerts(ref, cat).map((a) => a.id), alerts.map((a) => a.id));
  // an alert on an entity that has no row at all (no source, no discover prefix) is evaluated from the raw state too
  const lone = { ...bigStates(N), 'sensor.ecco_lone': mkState('sensor.ecco_lone', 'bad', {}) };
  const cat2 = validateCatalogue({ ...cat, alerts: [{ id: 'LONE', severity: 'critical', entity_id: 'sensor.ecco_lone', when: { state_in: ['bad'] }, text: 'Lone is bad.', action: 'x' }] }).catalogue;
  assert.deepEqual(deriveAlerts(buildSnapshot(lone, cat2, NOW), cat2).map((a) => a.id), ['LONE']);
});

test('AC12 [r8] the snapshot is DETERMINISTIC and the caches cannot show an unread entity as read or the reverse: the same states give the same rows; a row that was read is not given to an entity that is now past the budget; a row that was not read is read when there is room', () => {
  const N = 30;
  const cat = bigCatalogue(N);
  const states = bigStates(N);
  const a = buildSnapshot(states, cat, NOW);
  const b = buildSnapshot(states, cat, NOW);
  assert.deepEqual(b.rows.map((r) => [r.key, r.unread, r.spent]), a.rows.map((r) => [r.key, r.unread, r.spent]), 'the same states, the same snapshot (a cached row is charged what it cost)');
  assert.equal(b.counts.unread, a.counts.unread);
  const id = (i) => `sensor.ecco_big_${String(i).padStart(2, '0')}`;
  const firstUnread = a.rows.filter((r) => r.unread)[0];
  const lastRead = [...a.rows].reverse().find((r) => !r.unread);
  assert.ok(firstUnread && lastRead);
  // the entities before it shrink (a new state object each): there is room, so the one that was not read is read now
  const shrunk = { ...states };
  for (let i = 0; i < 5; i += 1) shrunk[id(i)] = mkState(id(i), 'ok', { small: 1 });
  const c = buildSnapshot(shrunk, cat, NOW);
  assert.equal(byEntity(c, firstUnread.entity_id).unread, false, 'an entity that was not read is read when the entities before it cost less');
  assert.ok(JSON.stringify(byEntity(c, firstUnread.entity_id).redacted).includes('zqmark'), 'and shows its text');
  // the entities before it cost more (twenty thousand values each, read before their text, a new state object each): the one that was read, and is cached, is past the budget now although its own state object is the same
  const heavy = {};
  for (let k = 0; k < 100; k += 1) heavy[`h${k}`] = Array.from({ length: 180 }, (_, i) => i);
  const grown = { ...states };
  for (let k = 0; k < 8; k += 1) grown[id(k)] = mkState(id(k), 'ok', { ...heavy, ...bigAttrs(`zqmark${String(k).padStart(2, '0')}x`) });
  const d = buildSnapshot(grown, cat, NOW);
  assert.equal(grown[lastRead.entity_id], states[lastRead.entity_id], 'the entity that was read last has the very same state object (its row and its parts are cached)');
  assert.equal(byEntity(d, lastRead.entity_id).unread, true, 'an entity that was read and cached is NOT read when the entities before it cost more');
  assert.ok(d.counts.unread > a.counts.unread);
  for (const r of d.rows.filter((x) => x.unread)) assert.ok(!JSON.stringify(r).includes('zqmark'), `${r.entity_id}: nothing of an unread entity`);
  const d2 = buildSnapshot(grown, cat, NOW);
  assert.deepEqual(d2.rows.map((r) => [r.key, r.unread]), d.rows.map((r) => [r.key, r.unread]), 'and it is the same again');
});

test('AC12 [r8] Production says so too: the summary names the data points that were not read, and says nothing of the kind when every entity was read', () => {
  const N = 30;
  const s = buildSnapshot(bigStates(N), bigCatalogue(N), NOW);
  const sum = summarise(s, []);
  assert.match(sum.note, new RegExp(`${s.counts.unread} data points were not read`));
  assert.ok(!/stale, unavailable, simulated or unverified/.test(sum.note), 'an unread entity is not counted as stale or unavailable');
  assert.ok(!summarise(snap(), []).note.includes('not read'), 'ordinary data: nothing of the kind');
  const one = buildSnapshot(bigStates(21), bigCatalogue(21), NOW);
  assert.equal(one.counts.unread, 1);
  assert.match(summarise(one, []).note, /1 data point was not read/);
});

test('AC12 [r8] ordinary data is not touched by the snapshot budget: every Intelligence fixture is read whole (nothing unread, no note), and what an entity costs is its size and no more', () => {
  const s = snap();
  assert.equal(s.counts.unread, 0);
  assert.equal(s.rows.filter((r) => r.unread).length, 0);
  for (const r of s.rows) {
    if (!r.present) assert.equal(r.spent, 0, `${r.entity_id}: an entity that does not exist costs nothing`);
    else {
      assert.ok(r.spent >= LIMITS.entityBaseChars, `${r.entity_id}: at least the base cost`);
      assert.ok(r.spent <= LIMITS.entityChars + 20000, `${r.entity_id}: at most the entity budget and the values it visited`);
    }
  }
  const total = s.rows.reduce((n, r) => n + r.spent, 0);
  assert.ok(total < LIMITS.snapshotChars / 20, `the whole Intelligence view costs ${total}, a twentieth of the budget at most`);
  assert.equal(summarise(s, []).note.includes('not read'), false);
});

test('AC12 [r8] what an entity costs: the characters it was read for, the values it visited, never less than the base cost, never more than its own budget plus its values', () => {
  const tiny = buildSnapshot({ 'sensor.ecco_big_00': mkState('sensor.ecco_big_00', 'ok', {}) }, bigCatalogue(1), NOW);
  assert.equal(tiny.rows[0].spent, LIMITS.entityBaseChars, 'a tiny entity costs the base cost');
  const heavy = {};
  for (let k = 0; k < 150; k += 1) heavy[`k${k}`] = Array.from({ length: 150 }, (_, i) => i);
  const h = buildSnapshot({ 'sensor.ecco_big_00': mkState('sensor.ecco_big_00', 'ok', heavy) }, bigCatalogue(1), NOW);
  assert.ok(h.rows[0].spent > 150 * 150 * LIMITS.nodeChars * 0.9, `a thousand values cost ${h.rows[0].spent}: the values it visited are charged`);
  const long = buildSnapshot({ 'sensor.ecco_big_00': mkState('sensor.ecco_big_00', 'ok', bigAttrs('zq')) }, bigCatalogue(1), NOW);
  assert.ok(long.rows[0].spent >= LIMITS.entityChars && long.rows[0].spent < LIMITS.entityChars + 100, `the characters it read are charged: ${long.rows[0].spent}`);
});

test('AC10 [r8] the id of an entity is read whether or not the entity is, and an id that cannot be a Home Assistant entity id (over 255 characters) is withheld unread', () => {
  const cat = validateCatalogue({ ...miniCatalogue(), sources: [], alerts: [] }).catalogue;
  const long = `sensor.ecco_intel_${'g'.repeat(300)}`; // letters no rule reads (a run of a is a hex run and would be withheld by that rule): only the cap can withhold this id
  const hostile = j('sensor.ecco_intel_', 'gh', 'p_', 'A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8');
  const s = buildSnapshot({ [long]: mkState(long, 'ok', {}), [hostile]: mkState(hostile, 'ok', {}), 'sensor.ecco_intel_fine': mkState('sensor.ecco_intel_fine', 'ok', {}) }, cat, NOW);
  assert.equal(s.rows.length, 3);
  assert.equal(s.rows.filter((r) => r.entity_id === WITHHELD).length, 2, 'the long id and the id that looks like a token are both withheld');
  assert.ok(s.rows.some((r) => r.entity_id === 'sensor.ecco_intel_fine'));
  assert.ok(!everything(s.rows).includes('g'.repeat(300)));
});
