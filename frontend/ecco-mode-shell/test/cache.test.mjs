// Review round 9 ([r9]): THE CACHE CLASS. The card caches in several places: the compiled catalogue (PREP), the compiled extra key patterns (EXTRA_CACHE), the per-entity key decisions of one read (ctx.keys), the
// read of one state object (PARTS: redacted attributes, attribute rows, search text, and what the read COST the snapshot), the built row (ROWS_BY_STATE, ROWS_BY_SOURCE) and, in the Geek surface, the rendered
// row (this.cache, by signature). The round-8 DETERMINISTIC test built two snapshots at the SAME clock, so the row cache hit and the parts cache (the normal path on every timer tick, when only the age moves) was
// never asked: reviewer mutant B11 (a row or parts reused from the cache is charged nothing) survived every suite, and with it the guarantee that the same states give the same snapshot.
//
// The class is "a cache returns something a cold read would not": stale, free or from the wrong key. So these tests do not name a cache. They ask, after EVERY step of a history, whether the snapshot built from
// WARM caches (the same state objects and catalogue object as the step before, as Home Assistant keeps them: an unchanged entity is the same object) is identical to the snapshot a COLD read gives (a deep copy of
// everything, so that every cache misses), and they walk the dimensions a cache can be wrong in: the clock (NOW, +61 s, +1 h, +2 h), a one-entity update, an entity that goes and comes back, a new entity that sorts
// before the others (every later row moves), a catalogue swapped under the same states (a title, a unit, a different set of secret key fragments), the snapshot budget (an entity before the cached one grows, so the cached
// one is now past the budget; or shrinks, so there is room again), and every Intelligence fixture. "Identical" is every field of every row (state, age, status, flags, order, unread, spent, attributes, the redacted
// values, the search text, the signature of the row) and the counts, the alert inputs, the alerts and the Production sentence.
import test from 'node:test';
import assert from 'node:assert/strict';
import { loadCard, miniCatalogue, miniStates, mkState, NOW, realCatalogue, intelFixtureNames, intelStates, noiseStates } from './helpers.mjs';
import { filler } from './secrets.mjs';

const core = await loadCard('cache9');
const { buildSnapshot, validateCatalogue, deriveAlerts, summarise, searchRows, LIMITS, STATS } = core;

// ---- what "the same snapshot" means
const SIG_PARTS_ID = 6; // the position of the read's sequence number in a row signature (the one part that differs between two reads of the same data)
const normSig = (sig) => String(sig).split('\u0001').map((x, i) => (i === SIG_PARTS_ID && /^[1-9]\d*$/.test(x) ? 'P' : x)).join('|');
const norm = (snap, cat) => ({
  rows: snap.rows.map(({ sig, ...r }) => ({ ...r, sig: normSig(sig) })),
  counts: snap.counts,
  groups: snap.groups,
  alertInputs: snap.alertInputs,
  watch: [...snap.watch].sort(),
  nowMs: snap.nowMs,
  alerts: deriveAlerts(snap, cat),
  summary: summarise(snap, deriveAlerts(snap, cat)),
  byKeys: [...snap.byKey.keys()],
});
const clone = (v) => structuredClone(v);

/**
 * Walk a history. A step is { label, t, states?, catalogue? }: `states` and `catalogue` are the NEW objects from that step on (omitted: the same objects as before, which is what Home Assistant gives for an
 * unchanged entity and the dashboard gives for an unchanged configuration). After each step the snapshot from warm caches is compared with a cold read of a deep copy, and a second warm read at the same
 * clock must be the same again.
 */
function walk(name, start, steps) {
  let states = start.states;
  let catalogue = start.catalogue;
  const seen = [];
  for (const step of steps) {
    if (step.states) states = typeof step.states === 'function' ? step.states(states) : step.states;
    if (step.catalogue) catalogue = step.catalogue;
    const label = `${name}: ${step.label}`;
    const warm = buildSnapshot(states, catalogue, step.t);
    const cold = buildSnapshot(clone(states), clone(catalogue), step.t);
    const again = buildSnapshot(states, catalogue, step.t);
    assert.deepEqual(norm(warm, catalogue), norm(cold, clone(catalogue)), `${label}: the snapshot from warm caches is not the one a cold read gives`);
    assert.deepEqual(norm(again, catalogue), norm(warm, catalogue), `${label}: the same states and clock, read twice, give two snapshots`);
    seen.push(norm(warm, catalogue));
  }
  return seen;
}

// ---------------------------------------------------------------------------------------------------------------------------
// (1) the mini Intelligence view: time, a one-entity update, an entity that goes and comes back, a new entity that sorts first, a catalogue swapped under the same states
// ---------------------------------------------------------------------------------------------------------------------------
const withCatalogue = (patch) => {
  const c = miniCatalogue();
  patch(c);
  const v = validateCatalogue(c);
  assert.equal(v.ok, true, JSON.stringify(v.errors));
  return v.catalogue;
};
const EXTRA_KEY = 'zzextra_note';
const EXTRA_TEXT = 'zzextra harmless words 4711';

test('AC12 [r9] CACHES: after every step of a history, the snapshot from warm caches is the snapshot a cold read gives, whatever the step: the clock (+61 s, +1 h, +2 h), a one-entity update, an entity that goes and comes back, a new entity that sorts first, a catalogue swapped under the same states', () => {
  const base = miniStates((s) => {
    s['sensor.ecco_intel_status'].attributes[EXTRA_KEY] = EXTRA_TEXT;
    s['sensor.ecco_intel_new_diagnostic'].attributes.note_for_nothing = 'plain words';
    s['sensor.ecco_intel_new_diagnostic'].attributes[EXTRA_KEY] = EXTRA_TEXT; // a DISCOVERED entity too: its read is cached under a constant reference, so only the catalogue check tells two catalogues apart
  });
  // the same entity described by TWO sources (a valid catalogue: only the source id must be unique) with different declared attributes and titles: one state object, two rows
  const catTwin = withCatalogue((c) => {
    c.redaction.extra_key_patterns = ['zzextra'];
    const s = c.sources[0];
    c.sources.push({ ...JSON.parse(JSON.stringify(s)), id: 'S99', title: 'Status again', description: 'The same entity, described a second time.', priority: 'normal', attributes: [{ name: 'mode', description: 'Only this one is declared.', unit: null, priority: 'normal' }] });
  });
  const shared = mkState('sensor.ecco_intel_twin_a', 'on', { friendly_name: 'Twin' }, { ageS: 12 });
  const catA = withCatalogue((c) => { c.redaction.extra_key_patterns = ['zzextra']; });
  const catB = withCatalogue((c) => { c.redaction.extra_key_patterns = []; c.sources[0].title = 'Status (renamed)'; c.sources[0].description = 'A new description of the status.'; });
  const t1 = NOW + 61000;
  const t2 = NOW + 3600000;
  const t3 = NOW + 7200000;
  const touched = (id, patch) => (s) => ({ ...s, [id]: { ...s[id], ...patch(s[id]) } });
  const seen = walk('mini', { states: base, catalogue: catA }, [
    { label: 'the first read', t: NOW },
    { label: 'a minute later (the row cache misses on the clock, the parts cache hits)', t: t1 },
    { label: 'an hour later (sources go stale)', t: t2 },
    { label: 'two hours later', t: t3 },
    { label: 'one entity updated (a new state object, the others the same objects)', t: t3 + 61000, states: touched('sensor.ecco_intel_status', (e) => ({ state: 'STALE', last_updated: new Date(t3 + 61000 - 5000).toISOString(), attributes: { ...e.attributes, mode: 'SHADOW', changed: 1 } })) },
    { label: 'the same, a minute later', t: t3 + 122000 },
    { label: 'an entity disappears', t: t3 + 122000, states: (s) => { const o = { ...s }; delete o['sensor.ecco_intel_charge_target']; return o; } },
    { label: 'and comes back as a new object', t: t3 + 183000, states: (s) => ({ ...s, 'sensor.ecco_intel_charge_target': mkState('sensor.ecco_intel_charge_target', '3.1', { unit_of_measurement: 'kWh' }, { ageS: 20 }) }) },
    { label: 'a new discovered entity that sorts BEFORE the others (every later discovered row moves)', t: t3 + 183000, states: (s) => ({ ...s, 'automation.ecco_intel_aaa_first': mkState('automation.ecco_intel_aaa_first', 'on', { friendly_name: 'First' }, { ageS: 10 }) }) },
    { label: 'and one that sorts last', t: t3 + 244000, states: (s) => ({ ...s, 'sensor.ecco_intel_zzz_last': mkState('sensor.ecco_intel_zzz_last', 'off', {}, { ageS: 10 }) }) },
    { label: 'the catalogue is swapped under the SAME state objects (a title, a description and the secret key fragments change)', t: t3 + 244000, catalogue: catB },
    { label: 'and a minute later', t: t3 + 305000 },
    { label: 'and swapped back', t: t3 + 305000, catalogue: catA },
    { label: 'the same entity described by two sources (one state object, two rows with different declared attributes and titles)', t: t3 + 305000, catalogue: catTwin },
    { label: 'and a minute later', t: t3 + 366000 },
    { label: 'two discovered entity ids that share ONE state object (the second must not be given the first one\'s row)', t: t3 + 366000, states: (s) => ({ ...s, 'sensor.ecco_intel_twin_a': shared, 'sensor.ecco_intel_twin_b': shared }) },
    { label: 'and a minute later', t: t3 + 427000 },
  ]);
  // the control: the steps really differ (a history that changes nothing proves nothing about a cache)
  const row = (i, id) => seen[i].rows.find((r) => r.id === id);
  assert.notEqual(row(0, 'S01').ageText, row(2, 'S01').ageText, 'the age moves with the clock');
  assert.equal(row(0, 'S01').status, 'LIVE');
  assert.equal(row(2, 'S01').status, 'STALE', 'an hour later the status sensor is stale');
  assert.equal(row(4, 'S01').stateText, 'STALE', 'the updated entity shows its new state');
  assert.equal(row(6, 'S02').status, 'NOT_MEASURED', 'the entity that went is not measured');
  const disc = (i) => seen[i].rows.filter((r) => r.discovered).map((r) => r.entity_id);
  assert.equal(disc(8)[0], 'automation.ecco_intel_aaa_first', 'the new entity is first among the discovered ones');
  assert.deepEqual(disc(8).slice(1), disc(7), 'and every other discovered row is still there, each one place later');
  assert.equal(disc(9).at(-1), 'sensor.ecco_intel_zzz_last', 'the last one is last');
  assert.deepEqual(disc(9).slice(0, -1), disc(8), 'and the others keep their order');
  assert.notDeepEqual(row(10, 'S01').title, row(9, 'S01').title, 'the catalogue swap changed a title');
  const extra = (i) => JSON.stringify(row(i, 'S01').redacted);
  assert.ok(!extra(9).includes(EXTRA_TEXT), 'under the catalogue with the fragment the text is withheld');
  assert.ok(extra(10).includes(EXTRA_TEXT), 'under the catalogue without it the same state object shows it');
  assert.ok(!extra(12).includes(EXTRA_TEXT), 'and withheld again after the swap back');
  const diag = (i) => JSON.stringify(seen[i].rows.find((r) => r.entity_id === 'sensor.ecco_intel_new_diagnostic').redacted);
  assert.ok(!diag(9).includes(EXTRA_TEXT) && diag(10).includes(EXTRA_TEXT) && !diag(12).includes(EXTRA_TEXT), 'the same for the discovered entity, whose read is cached under a constant reference');
  assert.equal(row(13, 'S99').title, 'Status again', 'the second source of the same entity has its own title');
  assert.equal(row(13, 'S01').title, 'Status', 'and the first keeps its own');
  assert.notDeepEqual(row(13, 'S99').attributes.map((a) => a.path), row(13, 'S01').attributes.map((a) => a.path), 'and its own declared attributes (one state object, two reads)');
  const twin = (i, id) => seen[i].rows.find((r) => r.entity_id === id);
  assert.ok(twin(15, 'sensor.ecco_intel_twin_a') && twin(15, 'sensor.ecco_intel_twin_b'), 'both ids have a row');
  assert.notEqual(twin(15, 'sensor.ecco_intel_twin_a').key, twin(15, 'sensor.ecco_intel_twin_b').key);
});

test('AC12 [r9] CACHES: every Intelligence fixture, with 300 unrelated and decoy entities beside it, at its own clock, a minute later and an hour later, in one history (so every read after the first is a warm one)', () => {
  const cat = validateCatalogue(realCatalogue()).catalogue;
  const noise = noiseStates();
  const steps = [];
  let first = null;
  for (const name of intelFixtureNames()) {
    const { states, now } = intelStates(name);
    const merged = { ...noise, ...states };
    if (first === null) first = { merged, now };
    steps.push({ label: `${name}`, t: now, states: merged });
    steps.push({ label: `${name}, a minute later`, t: now + 61000 });
    steps.push({ label: `${name}, an hour later`, t: now + 3600000 });
  }
  steps.push({ label: 'the first fixture again, as new objects', t: first.now, states: { ...noise, ...intelStates(intelFixtureNames()[0]).states } });
  const seen = walk('intelligence', { states: first.merged, catalogue: cat }, steps);
  assert.ok(seen.length >= 28, `${seen.length} steps`);
  assert.ok(new Set(seen.map((s) => JSON.stringify(s.counts))).size >= 5, 'the fixtures differ from each other: the history looks at more than one thing');
  assert.ok(seen.every((s) => s.rows.length >= 17), 'a row for every source, and every discovered entity besides');
});

// ---------------------------------------------------------------------------------------------------------------------------
// (2) the snapshot budget: what a read COSTS is kept with the read, so a cached read is charged what it cost
// ---------------------------------------------------------------------------------------------------------------------------
const bigCatalogue = (n) => {
  const sources = Array.from({ length: n }, (_, i) => ({
    id: `B${String(i).padStart(2, '0')}`, entity_id: `sensor.ecco_big_${String(i).padStart(2, '0')}`, group: 'g', title: `Big ${i}`, description: '', priority: 'normal', unit: null,
    expected_update_s: null, stale_after_s: 900, origin: 'integration', attributes: [],
  }));
  const v = validateCatalogue({
    schema: 'ecco-geek-catalogue/1', view_id: 'big', title: 'Big', contract: 'big/1', groups: [{ id: 'g', title: 'G', order: 1, description: '' }], sources,
    discover: { entity_prefixes: [], group: 'g', exclude_entity_ids: [] }, alerts: [], exceptions: [], redaction: { extra_key_patterns: [] },
  });
  assert.equal(v.ok, true, JSON.stringify(v.errors));
  return v.catalogue;
};
const bigId = (i) => `sensor.ecco_big_${String(i).padStart(2, '0')}`;
const bigAttrs = (marker) => {
  const a = {};
  for (let i = 0; i < 6; i += 1) a[`text_${i}`] = `${marker}${i} ${filler(19970)}`;
  return a;
};
const bigStates = (n, ageS = 30) => {
  const out = {};
  for (let i = 0; i < n; i += 1) out[bigId(i)] = mkState(bigId(i), 'ok', bigAttrs(`zqmark${String(i).padStart(2, '0')}x`), { ageS });
  return out;
};
const heavy = () => {
  const h = {};
  for (let k = 0; k < 100; k += 1) h[`h${k}`] = Array.from({ length: 180 }, (_, i) => i);
  return h;
};

test('AC12 [r9] the snapshot is DETERMINISTIC through every cache: the same states give the same keys, unread flags, spent values and statuses at NOW, a minute later, an hour later and after a one-entity update (reviewer mutant B11: a cached read was charged nothing, so a later snapshot read past the budget)', () => {
  const N = 40;
  const cat = bigCatalogue(N);
  const states = bigStates(N);
  const shape = (s) => s.rows.map((r) => [r.key, r.unread, r.spent, r.status, r.stateText === core.WITHHELD]);
  const a = buildSnapshot(states, cat, NOW);
  assert.ok(a.counts.unread >= 15 && a.counts.unread <= 25, `${a.counts.unread} entities are past the budget: the budget bites`);
  assert.ok(a.rows.filter((r) => !r.unread).every((r) => r.spent >= LIMITS.entityChars), 'a read entity of this size costs what its budget allows');
  // the SAME clock: the row cache hits (the round-8 test stopped here)
  assert.deepEqual(shape(buildSnapshot(states, cat, NOW)), shape(a), 'the same clock');
  // a minute later and an hour later: the row cache MISSES on the clock, the parts cache HITS (the normal path of every timer tick); the clock does not move the budget
  const built0 = STATS.partsBuilt;
  const b = buildSnapshot(states, cat, NOW + 61000);
  assert.equal(STATS.partsBuilt, built0, 'the parts were reused (this is the path the test is about)');
  assert.deepEqual(shape(b).map((x) => x.slice(0, 3)), shape(a).map((x) => x.slice(0, 3)), 'a minute later: the same keys, the same unread flags, the same spent values');
  assert.equal(b.counts.unread, a.counts.unread);
  const c = buildSnapshot(states, cat, NOW + 3600000);
  assert.equal(STATS.partsBuilt, built0, 'and an hour later');
  assert.deepEqual(shape(c).map((x) => x.slice(0, 3)), shape(a).map((x) => x.slice(0, 3)), 'an hour later: the same keys, the same unread flags, the same spent values');
  assert.deepEqual(c.rows.map((r) => r.status), a.rows.map((r) => (r.present && !r.unread ? 'STALE' : r.status)).map((s, i) => (c.rows[i].status === 'STALE' ? 'STALE' : s)), 'the statuses are the clock\'s: a minute and an hour only age them');
  for (const r of b.rows.filter((x) => x.unread)) assert.equal(r.stateText, core.WITHHELD, 'an entity that was not read is still not shown a minute later');
  for (const r of c.rows.filter((x) => x.unread)) assert.ok(!JSON.stringify(r).includes('zqmark'), 'and nothing of it an hour later');
  // a one-entity update: the first entity is replaced by a SMALL one (new object, new clock). Everything else is the same object. Cached reads keep their cost; the room it frees is used
  const small = { ...states, [bigId(0)]: mkState(bigId(0), 'ok', { small: 1 }, { ageS: 5 }) };
  const d = buildSnapshot(small, cat, NOW + 3600000);
  const dCold = buildSnapshot(clone(small), clone(cat), NOW + 3600000);
  assert.deepEqual(shape(d), shape(dCold), 'after a one-entity update, warm caches and a cold read agree on every key, flag, cost and status');
  assert.ok(d.counts.unread < a.counts.unread, 'the room that the smaller entity left was used: one more entity is read');
  assert.equal(d.rows.find((r) => r.entity_id === bigId(0)).spent, LIMITS.entityBaseChars, 'a small entity costs the base cost, not nothing');
  // and the cost of a cached read, on its own: the same state object read twice is charged twice the same
  const one = { [bigId(0)]: states[bigId(0)] };
  const c1 = buildSnapshot(one, bigCatalogue(1), NOW);
  const c2 = buildSnapshot(one, bigCatalogue(1), NOW + 61000);
  assert.equal(c1.rows[0].spent > 0, true);
  assert.equal(c2.rows[0].spent, c1.rows[0].spent, 'a cached read costs what the read cost');
});

test('AC12 [r9] CACHES under budget pressure: entities before a cached one grow and shrink, the clock moves, the objects are kept: after every step the snapshot from warm caches is the one a cold read gives', () => {
  const N = 30;
  const cat = bigCatalogue(N);
  const states = bigStates(N);
  const growth = (k) => {
    const g = { ...states };
    for (let i = 0; i < k; i += 1) g[bigId(i)] = mkState(bigId(i), 'ok', { ...heavy(), ...bigAttrs(`zqmark${String(i).padStart(2, '0')}x`) }, { ageS: 12 });
    return g;
  };
  const seen = walk('budget', { states, catalogue: cat }, [
    { label: 'the first read', t: NOW },
    { label: 'a minute later', t: NOW + 61000 },
    { label: 'an hour later', t: NOW + 3600000 },
    { label: 'eight early entities grow (twenty thousand values each): a read and cached one is now past the budget', t: NOW + 3600000, states: growth(8) },
    { label: 'and a minute later', t: NOW + 3661000 },
    { label: 'they shrink back to the very objects they were (the cached reads of those objects are used again)', t: NOW + 3661000, states },
    { label: 'and an hour later', t: NOW + 7261000 },
    { label: 'the last entity is updated (a new object at the end of the order)', t: NOW + 7261000, states: { ...states, [bigId(N - 1)]: mkState(bigId(N - 1), 'changed', bigAttrs('zqmark29x'), { ageS: 3 }) } },
    { label: 'five early ones are replaced by small ones: there is room again for the entities that were not read', t: NOW + 7322000, states: (s) => { const o = { ...s }; for (let i = 0; i < 5; i += 1) o[bigId(i)] = mkState(bigId(i), 'ok', { small: i }, { ageS: 4 }); return o; } },
  ]);
  const unread = seen.map((s) => s.counts.unread);
  assert.ok(unread[3] > unread[0], `growing entities push cached ones past the budget (${unread.join(', ')})`);
  assert.equal(unread[5], unread[0], 'and shrinking them back gives the first snapshot again');
  assert.ok(unread[8] < unread[5], 'and room again reads more');
});

// ---------------------------------------------------------------------------------------------------------------------------
// (3) the honesty of the Production sentence (the same snapshot, the other half of the round: an entity that was not read can also be unavailable or stale)
// ---------------------------------------------------------------------------------------------------------------------------
test('AC9 [r9] Production counts the problem sentence from the rows whose STATUS is not live, read or not, and the unread sentence from the rows that were not read: an entity that is both is in both (reviewer finding: five unavailable entities among ten unread were never said to be unavailable)', () => {
  const N = 30;
  const cat = bigCatalogue(N);
  const states = bigStates(N);
  for (let i = 25; i < 30; i += 1) states[bigId(i)] = mkState(bigId(i), 'unavailable', bigAttrs(`zqmark${i}x`), { ageS: 30 });
  states[bigId(24)] = mkState(bigId(24), 'ok', bigAttrs('zqmark24x'), { ageS: 5000 }); // stale (900 s), and past the budget
  const snap = buildSnapshot(states, cat, NOW);
  const unreadRows = snap.rows.filter((r) => r.unread);
  const notLive = snap.rows.filter((r) => r.status !== 'LIVE');
  assert.ok(unreadRows.length >= 8, `${unreadRows.length} not read`);
  assert.equal(notLive.length, 6, 'five unavailable and one stale');
  assert.ok(notLive.every((r) => r.unread), 'every one of them is also past the budget: that is the case');
  assert.equal(snap.counts.notLive, 6, 'the snapshot counts the rows whose status is not live, read or not');
  assert.equal(snap.counts.unread, unreadRows.length);
  assert.equal(snap.counts.problems, unreadRows.length, 'the Problems filter lists the unread ones (they include the six)');
  const sum = summarise(snap, []);
  assert.match(sum.note, /6 data points are stale, unavailable, simulated or unverified\./, 'the six are said, although none of them was read');
  assert.match(sum.note, new RegExp(`${unreadRows.length} data points were not read`), 'and so are the unread ones');
  assert.ok(sum.note.indexOf('6 data points') < sum.note.indexOf('not read'), 'the problem sentence comes first');
  // the same data with every entity small: nothing unread, the same six are said, and the unread sentence is gone
  const smallStates = {};
  for (let i = 0; i < N; i += 1) smallStates[bigId(i)] = mkState(bigId(i), i >= 25 ? 'unavailable' : 'ok', {}, { ageS: i === 24 ? 5000 : 30 });
  const small = buildSnapshot(smallStates, cat, NOW);
  assert.equal(small.counts.unread, 0);
  assert.equal(small.counts.notLive, 6);
  assert.match(summarise(small, []).note, /^6 data points are stale, unavailable, simulated or unverified\. Geek Mode lists them\.$/);
  // one that is live and unread is only in the second sentence; one that is unavailable and read is only in the first
  const live = buildSnapshot(bigStates(N), cat, NOW);
  assert.ok(live.counts.unread >= 8 && live.counts.notLive === 0);
  assert.doesNotMatch(summarise(live, []).note, /stale, unavailable/);
  assert.match(summarise(live, []).note, /data points were not read/);
  const readOnly = buildSnapshot({ [bigId(0)]: mkState(bigId(0), 'unavailable', {}, { ageS: 30 }), ...Object.fromEntries(Array.from({ length: 5 }, (_, i) => [bigId(i + 1), mkState(bigId(i + 1), 'ok', {}, { ageS: 30 })])) }, bigCatalogue(6), NOW);
  assert.equal(readOnly.counts.unread, 0);
  assert.match(summarise(readOnly, []).note, /^1 data point is stale, unavailable, simulated or unverified\. Geek Mode lists them\.$/);
  assert.doesNotMatch(summarise(readOnly, []).note, /not read/);
  // a snapshot with nothing to say says nothing
  assert.equal(summarise(buildSnapshot(smallStates, cat, NOW), []).note.includes('not read'), false);
  assert.equal(summarise({ counts: {} }, []).note, '');
  assert.equal(summarise(null, []).note, '');
  // the search still finds them by saying so
  assert.ok(searchRows(snap.rows, 'not read').length >= unreadRows.length);
});
