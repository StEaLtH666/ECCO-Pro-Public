// The pure core of the Mode Shell: mode controller, catalogue validation, classification, redaction, snapshot, alerts, search,
// windowing, export and the child-card guard. No DOM. Covers AC1/AC2/AC4 (controller), AC6 (alerts), AC8 (coverage), AC9
// (honesty), AC10 (redaction), AC11 (search), AC12 (performance), AC15 (card side of the coverage ledger) and AC16 (guard).
import test from 'node:test';
import assert from 'node:assert/strict';
import { loadCard, miniCatalogue, miniStates, miniStatesRaw, hostileStatesRaw, statesFrom, mkState, NOW } from './helpers.mjs';
import { SECRET_VALUES, SECRET_KEYS, SECRET_KEY_NAMES, KEY_MARKER, hostileAttributes, forbiddenStrings } from './secrets.mjs';

const core = await loadCard('core');
const {
  MODES, DEFAULT_MODE, WITHHELD, STATUSES, LIMITS, createModeController, buildSnapshot, deriveAlerts, classifyRow, redactAttributes,
  redactValue, countWithheld, searchRows, windowRows, exportRows, validateCatalogue, validateChildCards, validateConfig, cleanText,
  formatAge, summarise, catalogueItemIds, STATS,
} = core;

const cat = () => miniCatalogue();
const snap = (mutate = null, catalogue = cat()) => buildSnapshot(miniStates(mutate), validateCatalogue(catalogue).catalogue, NOW);
const row = (s, id) => s.rows.find((r) => r.id === id);
const byEntity = (s, eid) => s.rows.find((r) => r.entity_id === eid);
const dump = (v) => JSON.stringify(v);
const EXTRA = { extraKeyPatterns: ['^site_owner$'] };

// ---------------------------------------------------------------------------------------------------------------------------
// the exports
// ---------------------------------------------------------------------------------------------------------------------------
test('exports: the named pure functions and constants exist', () => {
  for (const f of [createModeController, buildSnapshot, deriveAlerts, classifyRow, redactAttributes, redactValue, searchRows, windowRows,
    exportRows, validateCatalogue, validateChildCards, validateConfig, cleanText, formatAge, summarise, catalogueItemIds, countWithheld]) {
    assert.equal(typeof f, 'function');
  }
  assert.deepEqual([...MODES], ['production', 'geek']);
  assert.equal(DEFAULT_MODE, 'production');
  assert.deepEqual([...STATUSES], ['LIVE', 'STALE', 'UNAVAILABLE', 'UNKNOWN', 'NOT_MEASURED', 'SIMULATED', 'UNVERIFIED']);
  assert.equal(typeof WITHHELD, 'string');
});

// ---------------------------------------------------------------------------------------------------------------------------
// AC1 / AC2 / AC4 (pure): the controller
// ---------------------------------------------------------------------------------------------------------------------------
test('AC1/AC2 controller: a new controller is Production; only the two modes are accepted; reset returns to Production', () => {
  const seen = [];
  const c = createModeController({ onChange: (m, why) => seen.push([m, why]) });
  assert.equal(c.mode, 'production');
  assert.equal(c.set('nonsense'), false);
  assert.equal(c.set(undefined), false);
  assert.equal(c.set('production'), false, 'no-op does not notify');
  assert.equal(c.set('geek'), true);
  assert.equal(c.mode, 'geek');
  assert.equal(c.reset(), true);
  assert.equal(c.mode, 'production');
  assert.equal(c.reset(), false);
  assert.deepEqual(seen, [['geek', 'set'], ['production', 'reset']]);
  assert.equal(createModeController().mode, 'production', 'a second controller (a reload) starts in Production again');
});

test('AC4 controller: two controllers never share a mode', () => {
  const a = createModeController();
  const b = createModeController();
  a.set('geek');
  assert.equal(a.mode, 'geek');
  assert.equal(b.mode, 'production');
  b.set('geek');
  a.reset();
  assert.equal(b.mode, 'geek');
});

// ---------------------------------------------------------------------------------------------------------------------------
// catalogue validation (AC16 fail-closed, interface 1)
// ---------------------------------------------------------------------------------------------------------------------------
test('validateCatalogue: the mini catalogue is valid and nothing is dropped', () => {
  const r = validateCatalogue(cat());
  assert.equal(r.ok, true, dump(r.errors));
  assert.equal(r.catalogue.sources.length, 13);
  assert.equal(r.catalogue.alerts.length, 7);
  assert.equal(r.catalogue.groups.length, 5);
});

test('validateCatalogue: unknown keys are tolerated (the catalogue is data, never code)', () => {
  const c = cat();
  c.future_field = { x: 1 };
  c.sources[0].future = 'y';
  c.sources[0].attributes[0].future = 'z';
  c.alerts[0].future = 1;
  assert.equal(validateCatalogue(c).ok, true);
});

test('validateCatalogue: an unknown schema fails closed (no inventory) but keeps the individually valid alerts', () => {
  const c = cat();
  c.schema = 'ecco-geek-catalogue/2';
  const r = validateCatalogue(c);
  assert.equal(r.ok, false);
  assert.ok(r.errors.some((e) => /schema/i.test(e.message)));
  assert.equal(r.catalogue.sources.length, 0);
  assert.equal(r.catalogue.alerts.length, 7, 'what is valid still drives the safety strip');
});

test('validateCatalogue: a malformed source is reported; a malformed alert is dropped and reported; the rest is kept', () => {
  const c = cat();
  delete c.sources[2].entity_id;
  c.alerts[1].severity = 'catastrophic';
  c.alerts.push({ id: 'A99', severity: 'info', entity_id: 'sensor.x', when: { weird: true }, text: 't', action: 'a' });
  const r = validateCatalogue(c);
  assert.equal(r.ok, false);
  assert.ok(r.errors.length >= 3);
  assert.ok(r.errors.every((e) => typeof e.path === 'string' && typeof e.message === 'string'));
  assert.equal(r.catalogue.alerts.length, 6, 'the two malformed alerts are dropped, six stay');
});

test('validateCatalogue: bad types fail closed, never throw', () => {
  for (const bad of [null, undefined, 5, 'x', [], {}, { schema: 'ecco-geek-catalogue/1' }, { schema: 'ecco-geek-catalogue/1', sources: 'no' }]) {
    const r = validateCatalogue(bad);
    assert.equal(r.ok, false);
    assert.ok(Array.isArray(r.errors) && r.errors.length > 0);
    assert.ok(r.catalogue && Array.isArray(r.catalogue.sources) && Array.isArray(r.catalogue.alerts));
  }
});

test('validateCatalogue: duplicate source ids, an unknown group and a bad priority are errors', () => {
  let c = cat();
  c.sources[1].id = 'S01';
  assert.equal(validateCatalogue(c).ok, false);
  c = cat();
  c.sources[1].group = 'no-such-group';
  assert.equal(validateCatalogue(c).ok, false);
  c = cat();
  c.sources[1].priority = 'urgent';
  assert.equal(validateCatalogue(c).ok, false);
  c = cat();
  c.sources[1].stale_after_s = -5;
  assert.equal(validateCatalogue(c).ok, false);
  c = cat();
  c.exceptions[0].reason = 'because';
  assert.equal(validateCatalogue(c).ok, false);
});

test('validateConfig: never throws; unknown keys tolerated; bad lists are reported', () => {
  assert.deepEqual(validateConfig({ type: 'custom:ecco-mode-shell', view_id: 'v', title: 'T', always: [], production: [], extra: 1 }).errors, []);
  const bad = validateConfig({ always: 'no', production: {}, page_size: 'x' });
  assert.ok(bad.errors.length >= 2);
  assert.deepEqual(bad.always, []);
  assert.equal(validateConfig(null).always.length, 0);
  assert.ok(validateConfig({ alerts_from: 'elsewhere' }).errors.length >= 1);
});

// ---------------------------------------------------------------------------------------------------------------------------
// AC9: classification is honest
// ---------------------------------------------------------------------------------------------------------------------------
const SRC = { id: 'T', entity_id: 'sensor.t', stale_after_s: 900, expected_update_s: 300, priority: 'normal', attributes: [] };
const st = (state, attributes = {}, ageS = 30) => mkState('sensor.t', state, attributes, { ageS });

test('AC9 classifyRow: each status is reached by its own condition', () => {
  assert.equal(classifyRow(SRC, st('12.5'), NOW).status, 'LIVE');
  assert.equal(classifyRow(SRC, st('12.5', {}, 5000), NOW).status, 'STALE');
  assert.equal(classifyRow(SRC, st('unavailable'), NOW).status, 'UNAVAILABLE');
  assert.equal(classifyRow(SRC, st('unknown'), NOW).status, 'UNKNOWN');
  assert.equal(classifyRow(SRC, undefined, NOW).status, 'NOT_MEASURED');
  assert.equal(classifyRow(SRC, null, NOW).status, 'NOT_MEASURED');
  assert.equal(classifyRow(SRC, st('1', { simulated: true }), NOW).status, 'SIMULATED');
  assert.equal(classifyRow(SRC, st('1', { verified: false }), NOW).status, 'UNVERIFIED');
  assert.equal(classifyRow(SRC, st('1', { provenance_ok: false }), NOW).status, 'UNVERIFIED');
});

test('AC9 classifyRow: staleness is the age beyond stale_after_s, inclusive boundary is live; no rule means never stale', () => {
  assert.equal(classifyRow(SRC, st('1', {}, 900), NOW).status, 'LIVE');
  assert.equal(classifyRow(SRC, st('1', {}, 901), NOW).status, 'STALE');
  const noRule = { ...SRC, stale_after_s: null };
  assert.equal(classifyRow(noRule, st('1', {}, 9e6), NOW).status, 'LIVE');
  assert.equal(classifyRow(noRule, st('1', {}, 9e6), NOW).ageMonitored, false);
  assert.equal(classifyRow(SRC, st('1', {}, 10), NOW).ageMonitored, true);
});

test('AC9 classifyRow: a stale value is never reported live; a stale simulated value is stale first and still flagged simulated', () => {
  const r = classifyRow(SRC, st('1', { simulated: true }, 5000), NOW);
  assert.equal(r.status, 'STALE');
  assert.ok(r.flags.includes('STALE') && r.flags.includes('SIMULATED'));
  assert.ok(!r.flags.includes('LIVE'));
});

test('AC9 classifyRow: an unavailable or unknown value outranks everything else and is never "live"', () => {
  const r = classifyRow(SRC, st('unavailable', { simulated: true }, 5000), NOW);
  assert.equal(r.status, 'UNAVAILABLE');
  assert.ok(!r.flags.includes('LIVE'));
});

test('AC9 classifyRow: a source with a freshness rule but no usable timestamp cannot be shown as live', () => {
  const noTs = { entity_id: 'sensor.t', state: '5', attributes: {} };
  assert.equal(classifyRow(SRC, noTs, NOW).status, 'UNVERIFIED');
  assert.equal(classifyRow({ ...SRC, stale_after_s: null }, noTs, NOW).status, 'LIVE');
  assert.equal(classifyRow(SRC, { ...noTs, last_updated: 'not a date' }, NOW).status, 'UNVERIFIED');
});

test('AC9 classifyRow: the simulated and unverified flags also accept the alternative spellings', () => {
  for (const a of [{ is_simulated: true }, { synthetic: true }, { provenance: 'SIMULATED' }, { data_source: 'synthetic' }]) {
    assert.equal(classifyRow(SRC, st('1', a), NOW).status, 'SIMULATED', dump(a));
  }
  for (const a of [{ unverified: true }, { provenance: 'UNVERIFIED' }]) assert.equal(classifyRow(SRC, st('1', a), NOW).status, 'UNVERIFIED', dump(a));
  assert.equal(classifyRow(SRC, st('1', { simulated: false, verified: true }), NOW).status, 'LIVE');
});

test('AC9 classifyRow: a timestamp slightly in the future (clock skew) is age 0, not a crash and not stale', () => {
  const r = classifyRow(SRC, st('1', {}, -30), NOW);
  assert.equal(r.status, 'LIVE');
  assert.equal(r.ageS, 0);
});

test('formatAge: plain words, no invented precision', () => {
  assert.equal(formatAge(2), 'just now');
  assert.equal(formatAge(42), '42 s ago');
  assert.equal(formatAge(125), '2 min ago');
  assert.equal(formatAge(3 * 3600 + 600), '3 h 10 min ago');
  assert.equal(formatAge(2 * 86400 + 5), '2 d ago');
  assert.equal(formatAge(null), 'age unknown');
  assert.equal(formatAge(-1), 'age unknown');
  assert.equal(formatAge(NaN), 'age unknown');
});

// ---------------------------------------------------------------------------------------------------------------------------
// AC10: redaction
// ---------------------------------------------------------------------------------------------------------------------------
test('AC10 redactValue: every secret-like value is withheld even under an innocent key', () => {
  for (const s of SECRET_VALUES) {
    assert.equal(redactValue(s.value, { key: 'note' }), WITHHELD, s.label);
    assert.equal(redactValue({ any: [s.value] }).any[0], WITHHELD, `${s.label} nested in a list`);
  }
});

test('AC10 redactAttributes: every secret-like key withholds its value whatever the value looks like', () => {
  const out = redactAttributes(Object.fromEntries(SECRET_KEYS.map((k) => [k, KEY_MARKER(k)])));
  for (const k of SECRET_KEYS) assert.equal(out[k], WITHHELD, k);
});

test('AC10 redactAttributes: nothing from the hostile object survives, anywhere in the output, as JSON or as search text', () => {
  const out = redactAttributes(hostileAttributes(), EXTRA);
  const text = dump(out);
  for (const f of forbiddenStrings()) assert.ok(!text.includes(f), `leaked: ${f.slice(0, 12)}`);
  assert.equal(out.benign, 'visible-benign-text', 'benign values are untouched');
  assert.equal(out.friendly_name, 'Hostile sensor');
  assert.ok(countWithheld(out) > 40, 'many values were withheld and counted');
});

test('AC10 redactAttributes: nested dicts and lists are walked; a list under a secret key is withheld as a whole', () => {
  const out = redactAttributes({ outer: { inner: { list: [{ token: 'abc' }, 'ok-value', [SECRET_VALUES[0].value]] } }, tokens: ['a', 'b'] });
  assert.equal(out.outer.inner.list[0].token, WITHHELD);
  assert.equal(out.outer.inner.list[1], 'ok-value');
  assert.equal(out.outer.inner.list[2][0], WITHHELD);
  assert.equal(out.tokens, WITHHELD);
});

test('AC10 redactAttributes: key NAMES that look secret are replaced by a marker, and the marker is stable and unique', () => {
  const out = redactAttributes({ byname: Object.fromEntries(SECRET_KEY_NAMES.map((n) => [n, 'v'])) });
  const keys = Object.keys(out.byname);
  assert.equal(keys.length, 2);
  for (const k of keys) assert.match(k, /^\[withheld key \d+\]$/);
  assert.equal(new Set(keys).size, 2);
  for (const n of SECRET_KEY_NAMES) assert.ok(!dump(out).includes(n));
});

test('AC10 redactAttributes: the catalogue extra_key_patterns are honoured; a bad or dangerous pattern is ignored, never thrown', () => {
  const out = redactAttributes({ site_owner: 'zq-owner', other: 'fine' }, { extraKeyPatterns: ['^site_owner$'] });
  assert.equal(out.site_owner, WITHHELD);
  assert.equal(out.other, 'fine');
  assert.doesNotThrow(() => redactAttributes({ a: 'b' }, { extraKeyPatterns: ['(', '[', '(a+)+$', 5, null, 'x'.repeat(500)] }));
  assert.equal(redactAttributes({ a: 'b' }, { extraKeyPatterns: ['(a+)+$'] }).a, 'b');
});

test('AC10 redaction does not over-withhold: contract attribute names and ordinary values pass through', () => {
  const names = ['applies_nothing', 'contract_version', 'coverage_7d', 'friendly_name', 'generated_at', 'kind', 'mode', 'n', 'reason_codes', 'status',
    'unit', 'unit_of_measurement', 'advice', 'blockers', 'confidence', 'engine_comparison', 'valid_until', 'device_class', 'options', 'accuracy',
    'calibration', 'config_hash', 'data_quality', 'decisions', 'drift', 'engine_version', 'input_ages', 'integration_version', 'last_good',
    'next_run_at', 'pause_control', 'plan', 'provenance_ok', 'self_test', 'tariff', 'value', 'current', 'id', 'last_triggered', 'editable',
    'icon', 'p10', 'p90', 'achievable_soc_pct', 'binding_constraint', 'buffer_pct', 'window', 'reserve', 'authority', 'basis', 'difference_pct',
    'blocker_codes', 'regime', 'planning_quantile', 'label', 'usable', 'at', 'day', 'source', 'notes', 'ratio', 'precharge_by', 'reserve_runout_at',
    'price_range', 'provenance', 'assumptions', 'baselines', 'range_gbp', 'mae_7d', 'I-D1', 'I-D9', 'headroom_ceiling_pct', 'inputs_used'];
  const out = redactAttributes(Object.fromEntries(names.map((n) => [n, 'plain-value'])));
  for (const n of names) assert.equal(out[n], 'plain-value', `key ${n}`);
  const values = ['2026-11-14T12:00:00.123456+00:00', '2026-11-14T23:30:00+00:00', '0.1.0', 'ecco-intel-entities/1', 'TARGET_FROM_DEMAND',
    'sensor.ecco_intel_status', 'automation.ecco_intel_alert_no_fresh_intelligence_result', '123e4567-e89b-12d3-a456-426614174000', '1:23:45',
    'mdi:shield-check', 'ECCO Intelligence charge target', 'average_of_seven_nights_overnight_demand_planning', 'I-D4', '12:30', '80.0', 'SHADOW'];
  for (const v of values) assert.equal(redactValue(v, { key: 'note' }), v, v);
});

test('AC10 redaction: a git revision is shown only under a revision key and only at the exact git length; the same hex elsewhere is withheld', () => {
  const sha = '0123456789abcdef0123456789abcdef01234567';
  assert.equal(redactValue(sha, { key: 'git_sha' }), sha);
  assert.equal(redactValue(sha, { key: 'note' }), WITHHELD);
  assert.equal(redactValue(`${sha}${sha.slice(0, 24)}`, { key: 'git_sha' }), WITHHELD, 'a longer hex blob under that key is still a blob');
  assert.equal(redactValue('a1b2c3d4e5f60718', { key: 'config_hash' }), 'a1b2c3d4e5f60718', 'a short fingerprint is not a blob');
});

test('AC10 redaction: huge values and structures are capped, with a marker, never an exception', () => {
  const big = 'x'.repeat(200000);
  const out = redactAttributes({ big, wide: Object.fromEntries(Array.from({ length: 5000 }, (_, i) => [`k${i}`, i])), long: Array.from({ length: 5000 }, (_, i) => i) });
  assert.ok(out.big.length < LIMITS.stringCap + 200);
  assert.match(out.big, /truncated/);
  assert.ok(Object.keys(out.wide).length <= LIMITS.dictKeys + 1);
  assert.ok(out.long.length <= LIMITS.listItems + 1);
  const cyc = { name: 'cycle' };
  cyc.self = cyc;
  assert.doesNotThrow(() => redactAttributes(cyc));
  assert.doesNotThrow(() => redactValue(() => 1));
  assert.doesNotThrow(() => redactValue(Symbol('s')));
});

test('AC10 redaction: a hostile key __proto__ cannot change the prototype of the output', () => {
  const out = redactAttributes(JSON.parse('{"__proto__": {"polluted": true}, "ok": 1}'));
  assert.equal(Object.getPrototypeOf(out), Object.prototype);
  assert.equal({}.polluted, undefined);
  assert.equal(out.polluted, undefined);
});

test('AC10 redaction is idempotent and deterministic', () => {
  const once = redactAttributes(hostileAttributes(), EXTRA);
  assert.deepEqual(redactAttributes(once, EXTRA), once);
  assert.deepEqual(redactAttributes(hostileAttributes(), EXTRA), once);
});

test('AC10 cleanText: control, zero-width and bidi characters become visible escapes; long text is truncated with a marker', () => {
  const out = cleanText('a\u0000b\u200bc\u202ed\u007f\ufeffe');
  assert.ok(!/[\u0000\u200b\u202e\u007f\ufeff]/.test(out));
  assert.match(out, /U\+200B/);
  assert.match(out, /U\+202E/);
  assert.equal(cleanText('plain text 123'), 'plain text 123');
  assert.equal(cleanText('line one\nline two\ttab'), 'line one\nline two\ttab', 'newline and tab are kept');
  const long = cleanText('y'.repeat(5000), 100);
  assert.ok(long.length < 200);
  assert.match(long, /truncated/);
});

// ---------------------------------------------------------------------------------------------------------------------------
// AC8 / AC9 / AC15: the snapshot is the one adapter; coverage and honesty
// ---------------------------------------------------------------------------------------------------------------------------
test('AC8 snapshot: every catalogue source has exactly one row with its ledger id, in catalogue order inside its group', () => {
  const s = snap();
  const c = cat();
  for (const src of c.sources) {
    const rows = s.rows.filter((r) => r.id === src.id);
    assert.equal(rows.length, 1, src.id);
    assert.equal(rows[0].group, src.group);
    assert.equal(rows[0].entity_id, src.entity_id);
    assert.equal(rows[0].discovered, false);
  }
  assert.equal(s.rows.filter((r) => !r.discovered).length, c.sources.length);
});

test('AC8 snapshot: each source has the right status for the fixture', () => {
  const s = snap();
  const want = { S01: 'LIVE', S02: 'LIVE', S03: 'LIVE', S04: 'STALE', S05: 'SIMULATED', S06: 'NOT_MEASURED', S07: 'UNAVAILABLE', S08: 'UNKNOWN',
    S09: 'LIVE', S10: 'LIVE', S11: 'LIVE', S12: 'LIVE', S13: 'UNVERIFIED' };
  for (const [id, status] of Object.entries(want)) assert.equal(row(s, id).status, status, id);
});

test('AC8 snapshot: every declared attribute path is reachable on its row, present or honestly absent', () => {
  const s = snap();
  for (const src of cat().sources) {
    const r = row(s, src.id);
    const paths = new Set(r.attributes.map((a) => a.path));
    for (const a of src.attributes) assert.ok(paths.has(a.name), `${src.id}: ${a.name}`);
  }
  const status = row(s, 'S01');
  const get = (p) => status.attributes.find((a) => a.path === p);
  assert.equal(get('next_run_at').present, false, 'declared but absent is shown as absent');
  assert.equal(get('next_run_at').declared, true);
  assert.equal(get('accuracy.n').present, true);
  assert.equal(get('accuracy.n').parent, 'accuracy');
  assert.equal(get('accuracy.n').depth, 1);
  assert.equal(get('accuracy.n').value, '12');
  assert.ok(get('accuracy'), 'the parent of a dotted path is listed too');
  assert.equal(get('accuracy').kind, 'dict');
});

test('AC8 snapshot: undeclared attributes and undeclared first-level keys are listed too (the card tolerates unknown extras)', () => {
  const status = row(snap(), 'S01');
  const get = (p) => status.attributes.find((a) => a.path === p);
  assert.equal(get('future_diagnostic_x').declared, false);
  assert.equal(get('future_diagnostic_x').present, true);
  assert.equal(get('future_diagnostic_x').value, '7');
  assert.equal(get('accuracy.unlisted_extra').declared, false);
  assert.equal(get('accuracy.unlisted_extra').value, '1');
  const charge = row(snap(), 'S02');
  assert.ok(charge.attributes.find((a) => a.path === 'advice.buffer_pct'));
  assert.ok(charge.attributes.find((a) => a.path === 'advice.window'), 'a second-level dict is a sub-row; deeper levels are in the raw view');
  assert.ok(!charge.attributes.find((a) => a.path === 'advice.window.start'), 'only the first nesting level is listed as sub-rows');
  assert.match(dump(charge.redacted), /deep/, 'deeper levels are in the redacted raw view');
});

test('AC8 snapshot: entities with a discover prefix that the catalogue does not describe appear in the Discovered group; others never do', () => {
  const s = snap();
  const disc = s.rows.filter((r) => r.discovered);
  assert.deepEqual(disc.map((r) => r.entity_id).sort(), [
    'automation.ecco_intel_alert_new_example', 'binary_sensor.ecco_intel_new_flag', 'sensor.ecco_intel_new_diagnostic']);
  for (const r of disc) {
    assert.equal(r.group, 'discovered');
    assert.match(r.id, /^discovered:/);
  }
  const all = s.rows.map((r) => r.entity_id);
  for (const never of ['sensor.other_thing', 'sensor.ecco_unrelated', 'light.example_lamp', 'sensor.ecco_intel_excluded_probe']) {
    assert.ok(!all.includes(never), never);
  }
  assert.equal(s.counts.discovered, 3);
});

test('AC8 snapshot: a brand-new ecco_intel_ entity is picked up by the next snapshot without any catalogue change', () => {
  const states = miniStates();
  const v = validateCatalogue(cat()).catalogue;
  const before = buildSnapshot(states, v, NOW).rows.length;
  states['sensor.ecco_intel_brand_new'] = mkState('sensor.ecco_intel_brand_new', '1', { friendly_name: 'Brand new' });
  const after = buildSnapshot(states, v, NOW);
  assert.equal(after.rows.length, before + 1);
  assert.equal(byEntity(after, 'sensor.ecco_intel_brand_new').group, 'discovered');
});

test('AC8 snapshot: a catalogue without a discover block discovers nothing; an entity claimed by a source is never also discovered', () => {
  const c = cat();
  delete c.discover;
  assert.equal(snap(null, c).rows.filter((r) => r.discovered).length, 0);
  const s = snap();
  assert.equal(s.rows.filter((r) => r.entity_id === 'sensor.ecco_intel_status').length, 1);
});

test('AC9 snapshot: unavailable, unknown and missing rows say so in words and show no value; nothing is fabricated', () => {
  const s = snap();
  const un = row(s, 'S07');
  const unk = row(s, 'S08');
  const missing = row(s, 'S06');
  assert.equal(un.stateText, 'Unavailable');
  assert.equal(unk.stateText, 'Unknown');
  assert.equal(missing.stateText, 'Not measured');
  assert.equal(missing.present, false);
  assert.equal(missing.ageS, null);
  assert.equal(missing.lastUpdated, null);
  assert.ok(missing.attributes.every((a) => a.present === false), 'no attribute of a missing entity is invented');
  assert.ok(missing.attributes.every((a) => !/\d/.test(a.value)), 'no number appears for a missing entity');
  assert.equal(missing.unitText, '');
  assert.equal(un.unitText, '', 'an unavailable value carries no unit either');
});

test('AC9 snapshot: a stale row keeps its last value but is labelled stale; its age is the real age', () => {
  const stale = row(snap(), 'S04');
  assert.equal(stale.status, 'STALE');
  assert.equal(stale.stateText, '6.2');
  assert.equal(stale.unitText, 'kWh');
  assert.equal(stale.ageS, 4000);
  assert.equal(stale.ageText, '1 h 6 min ago');
  assert.ok(stale.flags.includes('STALE'));
  assert.ok(!stale.flags.includes('LIVE'));
});

test('AC9 snapshot: counts add up and agree with the rows', () => {
  const s = snap();
  assert.equal(s.counts.total, s.rows.length);
  assert.equal(STATUSES.reduce((n, k) => n + s.counts[k], 0), s.rows.length);
  assert.equal(s.counts.STALE, 1);
  assert.equal(s.counts.UNAVAILABLE, 1);
  assert.equal(s.counts.NOT_MEASURED, 1);
  assert.equal(s.counts.problems, s.rows.filter((r) => r.problem).length);
  assert.equal(s.counts.withheld, 0);
});

test('AC10 snapshot: secrets in states never reach a row, the search text, the raw view or the withheld-aware counts', () => {
  const s = snap((states) => {
    states['sensor.ecco_intel_hostile'] = mkState('sensor.ecco_intel_hostile', SECRET_VALUES[0].value, hostileAttributes());
    states['sensor.ecco_intel_status'].attributes.api_key = KEY_MARKER('apikey');
    states['sensor.ecco_intel_status'].attributes.note = SECRET_VALUES[4].value;
  });
  const text = dump(s.rows);
  for (const f of forbiddenStrings()) assert.ok(!text.includes(f), `row data leaked ${f.slice(0, 10)}`);
  assert.ok(s.counts.withheld > 40);
  const hostile = byEntity(s, 'sensor.ecco_intel_hostile');
  assert.equal(hostile.stateText, WITHHELD, 'a secret-looking STATE is withheld too');
  for (const f of forbiddenStrings()) assert.ok(!hostile.searchText.includes(f.toLowerCase()), 'search index holds no secret');
  assert.equal(searchRows(s.rows, SECRET_VALUES[0].value).length, 0);
  assert.equal(searchRows(s.rows, 'hunter2').length, 0);
  assert.equal(searchRows(s.rows, KEY_MARKER('password')).length, 0);
});

test('AC10 snapshot: a discovered entity whose id or friendly name looks secret is shown withheld, never verbatim', () => {
  const evil = `sensor.ecco_intel_${SECRET_VALUES[1].value}`;
  const s = snap((states) => {
    states[evil] = mkState(evil, '1', { friendly_name: SECRET_VALUES[0].value });
  });
  const text = dump(s.rows);
  assert.ok(!text.includes(SECRET_VALUES[1].value));
  assert.ok(!text.includes(SECRET_VALUES[0].value));
  assert.equal(s.rows.filter((r) => r.discovered).length, 4, 'the entity is still listed, so it is not hidden, only its identity');
});

test('AC8/AC15 catalogueItemIds: every source id and every declared attribute path, for the ledger cross-check', () => {
  const ids = catalogueItemIds(validateCatalogue(cat()).catalogue);
  assert.ok(ids.includes('S01'));
  assert.ok(ids.includes('S01#accuracy.n'));
  assert.ok(ids.includes('S12#last_triggered'));
  assert.equal(new Set(ids).size, ids.length);
  assert.equal(ids.length, 13 + cat().sources.reduce((n, s) => n + s.attributes.length, 0));
});

test('AC7 snapshot: one adapter, one pass: the same states always give the same rows, and a changed state changes only its own row', () => {
  const c = validateCatalogue(cat()).catalogue;
  const states = miniStates();
  const a = buildSnapshot(states, c, NOW);
  const b = buildSnapshot(states, c, NOW);
  assert.deepEqual(a.rows.map((r) => r.sig), b.rows.map((r) => r.sig));
  const states2 = { ...states, 'sensor.ecco_intel_charge_target': mkState('sensor.ecco_intel_charge_target', '85.0', states['sensor.ecco_intel_charge_target'].attributes) };
  const d = buildSnapshot(states2, c, NOW);
  const changed = d.rows.filter((r, i) => r.sig !== a.rows[i].sig).map((r) => r.id);
  assert.deepEqual(changed, ['S02']);
  assert.equal(row(d, 'S02').stateText, '85.0');
});

test('buildSnapshot is total: any states shape (null, array, junk entries) gives a snapshot, never a throw', () => {
  const c = validateCatalogue(cat()).catalogue;
  for (const bad of [null, undefined, [], 'x', 5, { 'sensor.ecco_intel_status': null }, { 'sensor.ecco_intel_status': 'text' }, { 'sensor.ecco_intel_status': { state: 5 } },
    { 'sensor.ecco_intel_status': { state: 'OK', attributes: 'junk' } }, { 'sensor.ecco_intel_new': { state: 'x', attributes: null } }]) {
    const s = buildSnapshot(bad, c, NOW);
    assert.ok(Array.isArray(s.rows));
    assert.equal(s.rows.length >= c.sources.length, true);
  }
  assert.doesNotThrow(() => buildSnapshot(miniStates(), null, NOW));
  assert.doesNotThrow(() => buildSnapshot(miniStates(), {}, NOW));
  assert.equal(buildSnapshot(miniStates(), validateCatalogue({}).catalogue, NOW).rows.length, 0);
});

test('snapshot ordering: groups by catalogue order, headline signals first inside a group', () => {
  const s = snap();
  const groupOrder = s.groups.map((g) => g.id);
  assert.deepEqual(groupOrder, ['headline', 'advice', 'health', 'controls', 'discovered']);
  const health = s.rows.filter((r) => r.group === 'health').map((r) => r.priority);
  assert.deepEqual(health, [...health].sort((x, y) => ['headline', 'normal', 'obscure'].indexOf(x) - ['headline', 'normal', 'obscure'].indexOf(y)));
  assert.equal(s.rows[0].priority, 'headline');
  assert.equal(s.rows[s.rows.length - 1].discovered, true);
});

// ---------------------------------------------------------------------------------------------------------------------------
// AC6 (pure): the alert derivation
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
const alertsFor = (mutate = null, catalogue = cat()) => {
  const v = validateCatalogue(catalogue).catalogue;
  return deriveAlerts(buildSnapshot(miniStates(mutate), v, NOW), v);
};

test('AC6 deriveAlerts: a healthy system has no alert', () => {
  assert.deepEqual(alertsFor(), []);
});

for (const a of cat().alerts) {
  test(`AC6 deriveAlerts: ${a.id} (${a.severity}) fires when its condition holds, with its own text and action`, () => {
    const got = alertsFor(TRIGGER[a.id]).filter((x) => x.id === a.id);
    assert.equal(got.length, 1, `${a.id} must be active`);
    assert.equal(got[0].severity, a.severity);
    assert.equal(got[0].text, a.text);
    assert.equal(got[0].action, a.action);
    assert.equal(got[0].entity_id, a.entity_id);
  });

  for (const how of ['unavailable', 'unknown', 'missing']) {
    test(`AC6 deriveAlerts: ${a.id} - when ${a.entity_id} is ${how}, the strip is never silently clear`, () => {
      const got = alertsFor((s) => {
        if (how === 'missing') delete s[a.entity_id];
        else s[a.entity_id].state = how;
      });
      assert.ok(got.some((x) => x.entity_id === a.entity_id), `an alert about ${a.entity_id} must exist`);
    });
  }
}

test('AC6 deriveAlerts: an alert that cannot be evaluated is reported as such, at most as a warning, and is not repeated when an unavailable alert already covers the entity', () => {
  const got = alertsFor((s) => { s['binary_sensor.ecco_intel_watchdog_fresh'].state = 'unavailable'; });
  const u = got.find((x) => x.id === 'A03:unverifiable');
  assert.ok(u);
  assert.equal(u.kind, 'unverifiable');
  assert.equal(u.severity, 'warning');
  const status = alertsFor((s) => { s['sensor.ecco_intel_status'].state = 'unavailable'; });
  assert.ok(status.some((x) => x.id === 'A02' && x.severity === 'critical'));
  assert.ok(!status.some((x) => x.id === 'A01:unverifiable'), 'A02 already covers the unavailable status');
  assert.ok(!status.some((x) => x.id === 'A06:unverifiable'));
});

test('AC6 deriveAlerts: ordered critical, then warning, then info; stable inside a severity', () => {
  const got = alertsFor((s) => {
    TRIGGER.A05(s); TRIGGER.A03(s); TRIGGER.A01(s); TRIGGER.A07(s);
  });
  const rank = { critical: 0, warning: 1, info: 2 };
  const ranks = got.map((x) => rank[x.severity]);
  assert.deepEqual(ranks, [...ranks].sort((p, q) => p - q));
  assert.ok(got.length >= 4);
});

test('AC6 deriveAlerts: a stale or invalid catalogue still yields the alerts that are valid', () => {
  const c = cat();
  c.schema = 'ecco-geek-catalogue/9';
  assert.ok(alertsFor(TRIGGER.A01, c).some((x) => x.id === 'A01'));
});

test('AC6 deriveAlerts: a state_in list never matches an unrelated state; state_not_in treats unavailable as not in the list', () => {
  assert.ok(!alertsFor((s) => { s['sensor.ecco_intel_status'].state = 'OK'; }).some((x) => x.id === 'A01'));
  assert.ok(alertsFor((s) => { s['sensor.ecco_intel_status'].state = 'unknown'; }).some((x) => x.id === 'A04'));
});

test('AC6 deriveAlerts: the attribute condition compares the text of the attribute; booleans compare as true / false', () => {
  assert.ok(alertsFor(TRIGGER.A06).some((x) => x.id === 'A06'));
  assert.ok(!alertsFor((s) => { s['sensor.ecco_intel_status'].attributes.applies_nothing = true; }).some((x) => x.id === 'A06'));
  assert.ok(alertsFor((s) => { delete s['sensor.ecco_intel_status'].attributes.applies_nothing; }).some((x) => x.id === 'A06:unverifiable' || x.id === 'A06'),
    'an absent attribute is not silently fine');
});

test('summarise: plain words derived from the same snapshot and alert list', () => {
  const v = validateCatalogue(cat()).catalogue;
  const healthy = buildSnapshot(miniStates(), v, NOW);
  assert.equal(summarise(healthy, []).level, 'ok');
  const crit = alertsFor(TRIGGER.A01);
  assert.equal(summarise(healthy, crit).level, 'critical');
  assert.match(summarise(healthy, crit).text, /self-test/i);
  assert.equal(summarise(healthy, alertsFor(TRIGGER.A05)).level, 'info');
  assert.equal(summarise(healthy, alertsFor(TRIGGER.A03)).level, 'attention');
  assert.ok(summarise(healthy, []).text.length > 5);
});

// ---------------------------------------------------------------------------------------------------------------------------
// AC11: search, filter, window
// ---------------------------------------------------------------------------------------------------------------------------
test('AC11 searchRows: substring and multi-term search over id, title, state, attribute names and values (all terms must match)', () => {
  const rows = snap().rows;
  const ids = (q, f) => searchRows(rows, q, f).map((r) => r.id);
  assert.deepEqual(ids('charge target'), ['S02']);
  assert.ok(ids('ecco_intel_pv').includes('S03'));
  assert.deepEqual(ids('unavailable'), ['S07']);
  assert.ok(ids('target_soc').includes('S02'), 'attribute name');
  assert.ok(ids('cloudy morning').includes('S03'), 'attribute value, two terms');
  assert.ok(ids('git_sha').includes('S01'));
  assert.ok(ids('0123456789abcdef').includes('S01'), 'a public git revision is searchable');
  assert.deepEqual(ids('CHARGE   TARGET'), ['S02'], 'case and spacing are ignored');
  assert.deepEqual(ids('charge nonsense-term'), [], 'every term must match');
  assert.equal(ids('').length, rows.length);
  assert.equal(ids('   ').length, rows.length);
});

test('AC11 searchRows: filters by status, group, priority and problems, and they combine', () => {
  const rows = snap().rows;
  const ids = (f) => searchRows(rows, '', f).map((r) => r.id);
  assert.deepEqual(ids({ status: 'STALE' }), ['S04']);
  assert.deepEqual(ids({ status: 'NOT_MEASURED' }), ['S06']);
  assert.ok(ids({ status: 'SIMULATED' }).includes('S05'));
  assert.deepEqual(ids({ group: 'controls' }).sort(), ['S11', 'S12']);
  assert.ok(ids({ priority: 'obscure' }).includes('S12'));
  assert.ok(!ids({ problems: true }).includes('S01'));
  assert.ok(ids({ problems: true }).includes('S04'));
  assert.equal(ids({ problems: true }).length, rows.filter((r) => r.problem).length);
  assert.deepEqual(searchRows(rows, 'ecco_intel_overnight_demand', { status: 'LIVE' }).map((r) => r.id), []);
  assert.deepEqual(searchRows(rows, 'ecco_intel_overnight_demand', { status: 'STALE' }).map((r) => r.id), ['S04']);
  assert.equal(ids({ status: 'all', group: 'all', priority: 'all', problems: false }).length, rows.length);
});

test('AC11 searchRows: a stale simulated row is found by either status filter', () => {
  const s = snap((st2) => { st2['sensor.ecco_intel_export_event'] = mkState('sensor.ecco_intel_export_event', 'X', { simulated: true }, { ageS: 5000 }); });
  assert.ok(searchRows(s.rows, '', { status: 'STALE' }).some((r) => r.id === 'S05'));
  assert.ok(searchRows(s.rows, '', { status: 'SIMULATED' }).some((r) => r.id === 'S05'));
});

test('AC11 windowRows: pages are slices; the page is clamped; the totals are right', () => {
  const rows = Array.from({ length: 103 }, (_, i) => ({ i }));
  const w0 = windowRows(rows, 0, 25);
  assert.equal(w0.rows.length, 25);
  assert.equal(w0.pageCount, 5);
  assert.equal(w0.total, 103);
  assert.equal(w0.start, 0);
  assert.equal(w0.end, 25);
  const wLast = windowRows(rows, 4, 25);
  assert.equal(wLast.rows.length, 3);
  assert.equal(wLast.rows[0].i, 100);
  assert.equal(windowRows(rows, 99, 25).page, 4);
  assert.equal(windowRows(rows, -3, 25).page, 0);
  assert.equal(windowRows(rows, NaN, 25).page, 0);
  assert.equal(windowRows([], 0, 25).pageCount, 1);
  assert.equal(windowRows([], 0, 25).rows.length, 0);
  assert.ok(windowRows(rows, 0, 100000).rows.length <= LIMITS.maxPageSize);
  assert.ok(windowRows(rows, 0, 0).rows.length >= 1);
});

// ---------------------------------------------------------------------------------------------------------------------------
// export
// ---------------------------------------------------------------------------------------------------------------------------
test('exportRows json: a schema-tagged document of the displayed, redacted data, with absent attributes listed', () => {
  const s = snap();
  const doc = JSON.parse(exportRows(s.rows, 'json', { viewId: 'intelligence', nowMs: NOW }));
  assert.equal(doc.schema, 'ecco-geek-export/1');
  assert.equal(doc.view_id, 'intelligence');
  assert.equal(doc.generated_at, new Date(NOW).toISOString());
  assert.equal(doc.count, s.rows.length);
  const st4 = doc.rows.find((r) => r.id === 'S04');
  assert.equal(st4.status, 'STALE');
  assert.equal(st4.state, '6.2');
  assert.equal(st4.unit, 'kWh');
  const missing = doc.rows.find((r) => r.id === 'S06');
  assert.equal(missing.state, null, 'a missing entity exports no value');
  assert.equal(missing.status, 'NOT_MEASURED');
  const status = doc.rows.find((r) => r.id === 'S01');
  assert.ok(status.absent_attributes.includes('next_run_at'));
});

test('exportRows csv: a header, one line per row, quoting, and formula-injection neutralised', () => {
  const s = snap((states) => {
    states['sensor.ecco_intel_new_diagnostic'].attributes.friendly_name = '=HYPERLINK("x")';
    states['sensor.ecco_intel_new_diagnostic'].state = '+1,2"3';
  });
  const csv = exportRows(s.rows, 'csv');
  const lines = csv.trim().split('\n');
  assert.match(lines[0], /^id,entity_id,group,title,status,state,unit,age_s,attributes$/);
  assert.ok(lines.length >= s.rows.length + 1);
  assert.ok(!/(^|,)"?=HYPERLINK/.test(csv), 'a cell never starts with = + - @');
  assert.match(csv, /'\+1,2""3/);
});

test('AC10 exportRows: the export bytes contain no secret, even from a hand-made unsafe row (defence in depth)', () => {
  const s = snap((states) => {
    states['sensor.ecco_intel_hostile'] = mkState('sensor.ecco_intel_hostile', SECRET_VALUES[2].value, hostileAttributes());
  });
  for (const fmt of ['json', 'csv']) {
    const bytes = exportRows(s.rows, fmt, { nowMs: NOW });
    for (const f of forbiddenStrings()) assert.ok(!bytes.includes(f), `${fmt} leaked ${f.slice(0, 10)}`);
  }
  const unsafe = { ...s.rows[0], stateText: SECRET_VALUES[1].value, title: SECRET_VALUES[0].value, entity_id: SECRET_VALUES[4].value,
    redacted: { token: 'abc', note: SECRET_VALUES[5].value, nested: { k: [SECRET_VALUES[7].value] } } };
  for (const fmt of ['json', 'csv']) {
    const bytes = exportRows([unsafe], fmt, { nowMs: NOW });
    for (const v of [SECRET_VALUES[1].value, SECRET_VALUES[0].value, SECRET_VALUES[4].value, SECRET_VALUES[5].value, SECRET_VALUES[7].value, 'abc']) {
      assert.ok(!bytes.includes(v), `${fmt} leaked from an unsafe row`);
    }
  }
});

test('exportRows rejects an unknown format and tolerates empty input', () => {
  assert.throws(() => exportRows([], 'xml'));
  assert.equal(JSON.parse(exportRows([], 'json')).count, 0);
  assert.equal(exportRows([], 'csv').trim().split('\n').length, 1);
});

// ---------------------------------------------------------------------------------------------------------------------------
// AC16: the child-card guard
// ---------------------------------------------------------------------------------------------------------------------------
const intelCard = { type: 'custom:ecco-intelligence-card', title: 'ECCO Intelligence', entities: { status: 'sensor.ecco_intel_status' } };
const pauseTile = { type: 'tile', entity: 'input_boolean.ecco_intel_paused', name: 'Pause', tap_action: { action: 'toggle' }, icon_tap_action: { action: 'toggle' }, hold_action: { action: 'more-info' } };

test('AC16 validateChildCards: the read-only Intelligence card passes; the pause tile (a toggle) is refused in a Geek-visible region', () => {
  assert.equal(validateChildCards([intelCard]).ok, true);
  const r = validateChildCards([intelCard, pauseTile]);
  assert.equal(r.ok, false);
  assert.deepEqual(r.errors.map((e) => e.index), [1, 1]);
  assert.deepEqual(r.allowed, [0]);
  assert.ok(r.errors.some((e) => e.action === 'toggle'));
});

test('AC16 validateChildCards: the existing dashboard watchdog and status entities card (read-only rows) passes in a Geek-visible region', () => {
  const entities = { type: 'entities', title: 'Watchdog and status', show_header_toggle: false, state_color: true, entities: [
    { entity: 'binary_sensor.ecco_intel_watchdog_fresh', name: 'Watchdog (fresh, recognised result)' }, { entity: 'binary_sensor.ecco_intel_fresh', name: 'Integration reports fresh' },
    { entity: 'sensor.ecco_intel_status', name: 'Status' }, { entity: 'sensor.ecco_intel_data_quality', name: 'Data quality' }] };
  assert.equal(validateChildCards([entities]).ok, true);
  assert.equal(validateChildCards([{ ...entities, entities: [...entities.entities, { entity: 'input_boolean.ecco_intel_paused' }] }]).ok, false, 'adding the pause helper row would add a toggle');
});

test('AC16 validateChildCards: only none, more-info and navigate are allowed actions, under every action key and nesting', () => {
  const ok = (cfg) => validateChildCards([cfg]).ok;
  for (const a of ['none', 'more-info', 'navigate']) {
    assert.equal(ok({ type: 'markdown', content: 'x', tap_action: { action: a } }), true, a);
    assert.equal(ok({ type: 'glance', entities: ['sensor.x'], hold_action: { action: a }, double_tap_action: { action: a } }), true, a);
  }
  for (const a of ['toggle', 'call-service', 'perform-action', 'url', 'assist', 'fire-dom-event', 'repeat', 'anything-else']) {
    assert.equal(ok({ type: 'markdown', tap_action: { action: a } }), false, `tap ${a}`);
    assert.equal(ok({ type: 'markdown', hold_action: { action: a } }), false, `hold ${a}`);
    assert.equal(ok({ type: 'markdown', double_tap_action: { action: a } }), false, `double ${a}`);
    assert.equal(ok({ type: 'tile', entity: 'sensor.x', icon_tap_action: { action: a } }), false, `icon ${a}`);
    assert.equal(ok({ type: 'vertical-stack', cards: [{ type: 'horizontal-stack', cards: [{ type: 'markdown', tap_action: { action: a } }] }] }), false, `nested ${a}`);
    assert.equal(ok({ type: 'conditional', conditions: [], card: { type: 'markdown', tap_action: { action: a } } }), false, `conditional ${a}`);
    assert.equal(ok({ type: 'picture-elements', elements: [{ type: 'icon', tap_action: { action: a } }] }), false, `element ${a}`);
  }
});

test('AC16 validateChildCards: service-call shaped keys, write-capable card types and writable entity rows are refused', () => {
  const ok = (cfg) => validateChildCards([cfg]).ok;
  assert.equal(ok({ type: 'markdown', service: 'light.turn_on' }), false);
  assert.equal(ok({ type: 'markdown', perform_action: 'light.turn_on' }), false);
  assert.equal(ok({ type: 'markdown', tap_action: { perform_action: 'light.turn_on' } }), false);
  assert.equal(ok({ type: 'markdown', tap_action: { action: 'none', service: 'light.turn_on' } }), false, 'a hidden service next to a safe action');
  for (const t of ['button', 'light', 'thermostat', 'humidifier', 'media-control', 'alarm-panel', 'shopping-list', 'iframe', 'webpage']) {
    assert.equal(ok({ type: t, entity: 'sensor.x' }), false, t);
  }
  assert.equal(ok({ type: 'entities', entities: ['input_boolean.ecco_intel_paused'] }), false, 'an entities row of a writable domain shows a toggle');
  assert.equal(ok({ type: 'entities', entities: [{ entity: 'switch.x' }] }), false);
  assert.equal(ok({ type: 'entities', entities: [{ entity: 'input_select.x' }] }), false);
  assert.equal(ok({ type: 'entities', entities: [{ type: 'button', name: 'Go' }] }), false);
  assert.equal(ok({ type: 'entities', entities: [{ type: 'weblink', url: 'x' }] }), false);
  assert.equal(ok({ type: 'entities', entities: ['sensor.ecco_intel_status', 'binary_sensor.ecco_intel_fresh', { entity: 'sensor.x', secondary_info: 'last-changed' }] }), true);
  assert.equal(ok({ type: 'entities', entities: [{ entity: 'input_boolean.x', type: 'simple-entity' }] }), true, 'a simple-entity row is read-only');
  assert.equal(ok({ type: 'tile', entity: 'input_boolean.x' }), false, 'a tile on a writable domain needs explicit safe actions');
  assert.equal(ok({ type: 'tile', entity: 'input_boolean.x', tap_action: { action: 'more-info' }, icon_tap_action: { action: 'none' } }), true);
  assert.equal(ok({ type: 'tile', entity: 'sensor.x' }), true);
  assert.equal(ok({ type: 'tile', entity: 'sensor.x', features: [{ type: 'cover-open-close' }] }), false);
});

test('AC16 validateChildCards: junk is refused, never thrown on', () => {
  for (const bad of [null, 5, 'x', [], { type: 5 }, {}, { type: '' }]) {
    const r = validateChildCards([bad]);
    assert.equal(r.ok, false);
  }
  assert.equal(validateChildCards('not a list').ok, false);
  assert.equal(validateChildCards([]).ok, true);
  assert.equal(validateChildCards(undefined).ok, true);
  const cyc = { type: 'markdown' };
  cyc.self = cyc;
  assert.doesNotThrow(() => validateChildCards([cyc]));
});

// ---------------------------------------------------------------------------------------------------------------------------
// AC12 (pure): performance and caps
// ---------------------------------------------------------------------------------------------------------------------------
function bigStates(n) {
  const states = miniStates();
  for (let i = 0; i < n; i += 1) {
    const id = `sensor.ecco_intel_synth_${String(i).padStart(5, '0')}`;
    states[id] = mkState(id, String(i), {
      friendly_name: `Synthetic ${i}`, unit_of_measurement: 'kWh', reason_codes: ['A', 'B'], advice: { a: i, b: 'text', c: { d: 1 } },
      generated_at: '2026-11-14T11:59:20+00:00', status: 'OK', kind: 'synthetic', mode: 'SHADOW', applies_nothing: true,
    });
  }
  for (let i = 0; i < 2000; i += 1) states[`sensor.other_${i}`] = mkState(`sensor.other_${i}`, String(i), { friendly_name: `Other ${i}` });
  return states;
}

test('AC12 performance: 5000 synthetic entities snapshot within a generous budget; the search is fast; outside-prefix entities cost nothing', () => {
  const c = validateCatalogue(cat()).catalogue;
  const states = bigStates(5000);
  let t = performance.now();
  const s = buildSnapshot(states, c, NOW);
  const build = performance.now() - t;
  assert.equal(s.rows.length, 13 + 3 + 5000);
  assert.ok(build < 8000, `first snapshot took ${build.toFixed(0)} ms`);
  t = performance.now();
  const hits = searchRows(s.rows, 'synthetic 4999');
  const search = performance.now() - t;
  assert.equal(hits.length, 1);
  assert.ok(search < 500, `search took ${search.toFixed(0)} ms`);
  t = performance.now();
  const again = buildSnapshot(states, c, NOW);
  const rebuild = performance.now() - t;
  assert.equal(again.rows.length, s.rows.length);
  assert.ok(rebuild < build, `a cached rebuild (${rebuild.toFixed(0)} ms) is faster than the first (${build.toFixed(0)} ms)`);
});

test('AC12 performance: updating one entity recomputes one row, the rest come from the cache', () => {
  const c = validateCatalogue(cat()).catalogue;
  const states = bigStates(1500);
  buildSnapshot(states, c, NOW);
  const before = STATS.partsBuilt;
  const id = 'sensor.ecco_intel_synth_00007';
  const states2 = { ...states, [id]: mkState(id, 'changed', states[id].attributes) };
  const s2 = buildSnapshot(states2, c, NOW);
  assert.equal(STATS.partsBuilt - before, 1);
  assert.equal(byEntity(s2, id).stateText, 'changed');
  const before2 = STATS.partsBuilt;
  buildSnapshot(states2, c, NOW + 60000);
  assert.equal(STATS.partsBuilt - before2, 0, 'a later clock alone recomputes only the age-dependent fields');
});

test('AC12 caps: an attribute far larger than the cap is truncated with a marker in the row, the raw text and the export', () => {
  const huge = 'q'.repeat(600000);
  const s = snap((states) => {
    states['sensor.ecco_intel_new_diagnostic'].attributes.huge = huge;
    states['sensor.ecco_intel_new_diagnostic'].attributes.many = Array.from({ length: 9000 }, (_, i) => `item ${i}`);
  });
  const r = byEntity(s, 'sensor.ecco_intel_new_diagnostic');
  const a = r.attributes.find((x) => x.path === 'huge');
  assert.ok(a.value.length < LIMITS.value + 120);
  assert.equal(a.truncated, true);
  assert.match(a.value, /truncated/);
  const exported = exportRows([r], 'json', { nowMs: NOW });
  assert.ok(exported.length < 200000, `export is bounded (${exported.length} bytes)`);
  assert.ok(!exported.includes(huge.slice(0, LIMITS.stringCap + 50)));
  assert.ok(r.searchText.length < 400000);
});

test('AC12 caps: a hostile entity with thousands of attributes lists at most the cap and says how many more', () => {
  const s = snap((states) => {
    states['sensor.ecco_intel_new_diagnostic'].attributes = Object.fromEntries(Array.from({ length: 3000 }, (_, i) => [`attr_${i}`, i]));
  });
  const r = byEntity(s, 'sensor.ecco_intel_new_diagnostic');
  assert.ok(r.attributes.length <= LIMITS.attrsPerRow + 1);
  assert.ok(r.attrTotal >= 3000 || r.attrTotal > LIMITS.attrsPerRow);
  assert.match(r.attributes[r.attributes.length - 1].value + r.attributes[r.attributes.length - 1].name, /more/);
});

test('hostile fixture text is carried as plain strings (the card escapes by never building markup)', () => {
  const raw = hostileStatesRaw();
  const states = statesFrom(raw);
  const v = validateCatalogue(cat()).catalogue;
  const s = buildSnapshot({ ...miniStates(), ...states }, v, NOW);
  const r = byEntity(s, 'sensor.ecco_intel_hostile_markup');
  assert.ok(r);
  assert.ok(r.stateText.includes('<script>'), 'the text is kept as text');
  assert.ok(r.attributes.some((a) => a.name.includes('<b>bold</b>')), 'a hostile key is kept as text');
  const control = byEntity(s, 'sensor.ecco_intel_hostile_control');
  assert.ok(!/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]/.test(control.stateText));
  for (const a of control.attributes) assert.ok(!/[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u200b-\u200f\u202a-\u202e\u2066-\u2069\u2028\u2029\ufeff]/.test(a.value), a.path);
});
