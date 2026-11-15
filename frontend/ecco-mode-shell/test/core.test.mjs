// The pure core of the Mode Shell: mode controller, catalogue validation, classification, redaction, snapshot, alerts, search,
// windowing, export and the child-card guard. No DOM. Covers AC1/AC2/AC4 (controller), AC6 (alerts), AC8 (coverage), AC9
// (honesty), AC10 (redaction), AC11 (search), AC12 (performance), AC15 (card side of the coverage ledger) and AC16 (guard).
import test from 'node:test';
import assert from 'node:assert/strict';
import { loadCard, miniCatalogue, miniStates, miniStatesRaw, hostileStatesRaw, statesFrom, mkState, NOW } from './helpers.mjs';
import { SECRET_VALUES, SECRET_VALUES_R3, SECRET_VALUES_R4, SECRET_KEYS, SECRET_KEYS_R3, SECRET_KEY_NAMES, KEY_MARKER, hostileAttributes, forbiddenStrings } from './secrets.mjs';

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

// ===========================================================================================================================
// Review round 1 ([r1]): each test below was written to FAIL on the card as reviewed and to pass with its fix
// ===========================================================================================================================
const isoAt = (ms) => new Date(ms).toISOString();
const ZW = String.fromCharCode(0x200b); // zero-width space
const CYR_A = String.fromCharCode(0x430); // Cyrillic small a, a homoglyph of Latin a
const GREEK_O = String.fromCharCode(0x3bf); // Greek small omicron, a homoglyph of Latin o

test('AC10 [r1] a key that ends in a key word after a qualifier withholds even a SHORT value; look-alikes that are not keys pass', () => {
  for (const k of ['encryption_key', 'ssh_key', 'wifi_key', 'license_key', 'encryptionKey', 'sshKey', 'ENCRYPTION_KEY', 'wifi-psk', 'pin', 'psk', 'pin_code', 'owner.pin']) {
    assert.equal(redactValue('abc', { key: k }), WITHHELD, k);
    assert.equal(redactAttributes({ [k]: 'ab' })[k], WITHHELD, `${k} as an attribute`);
  }
  for (const k of ['keyboard_layout', 'monkey', 'turkey', 'key_count', 'keystone', 'hotkey', 'friendly_name', 'pinned', 'spin', 'pinball', 'key', 'keys_pressed']) {
    assert.equal(redactValue('plain', { key: k }), 'plain', k);
  }
});

test('AC10 [r1] zero-width characters and homoglyphs in a KEY name do not hide the key word, and the shown key name is escaped', () => {
  const names = [`pass${ZW}word`, `p${CYR_A}ssword`, `t${GREEK_O}ken`, `api${ZW}_key`, `pa${ZW}ss${ZW}wd`];
  const out = redactAttributes({ ...Object.fromEntries(names.map((n) => [n, 'plain'])), note: 'plain' });
  assert.equal(Object.keys(out).length, names.length + 1, 'the five names stay distinct');
  for (const [k, v] of Object.entries(out)) {
    if (k === 'note') assert.equal(v, 'plain');
    else assert.equal(v, WITHHELD, `value under ${JSON.stringify(k)}`);
  }
  assert.ok(Object.keys(out).every((k) => !k.includes(ZW)), 'a zero-width character is shown as a visible escape');
});

test('AC10 [r1] zero-width characters inside a VALUE do not hide a secret: they are stripped before matching, and still shown as escapes elsewhere', () => {
  const jwt = SECRET_VALUES.find((s) => s.label === 'jwt split by a zero-width character').value;
  assert.ok(jwt.includes(ZW));
  assert.equal(redactValue(jwt, { key: 'note' }), WITHHELD);
  const plain = `a${ZW}b`;
  assert.equal(redactValue(plain, { key: 'note' }), 'a' + String.fromCharCode(0x2039) + 'U+200B' + String.fromCharCode(0x203a) + 'b', 'a harmless value with a zero-width character is kept, with the character made visible');
});

test('AC10 [r1] values that look like a private host, a coordinate or a credential only by shape are withheld; ordinary text near those shapes is not', () => {
  for (const v of ['ws://homeassistant:8123/api/websocket', 'http://nas/share', 'https://intranet', 'home 52.1 N 0.12 W', '51.5074 N, 0.1278 W', "{'token': 'abc123def'}", '{"password":"abc123"}', 'lat 51.5074 lon -0.1278', 'latitude=51.5074', 'LON: -0.12780']) {
    assert.equal(redactValue(v, { key: 'note' }), WITHHELD, v);
  }
  for (const v of ['https://www.example.com:8443/x', 'http://example.com/a', 'latency 12.345 ms', 'plate 51.5074 mm', 'Chat 12.3456', 'ws://', 'the pin is not a secret here', 'a token of thanks',
    'password protected: no', 'lat 5', 'longitude is a word', 'row 5 N units 3 E apart', 'Plan 5 NE 3 SW', 'N 5 E 3']) {
    assert.equal(redactValue(v, { key: 'note' }), v, v);
  }
});

test('AC10 [r1] the hostile edge values hold on every path: row text, raw attributes, the search index and the export carry none of them', () => {
  const edge = SECRET_VALUES.slice(21, 32);
  assert.equal(edge.length, 11, 'eleven review-round edge values');
  const s = snap((states) => {
    states['sensor.ecco_intel_hostile'] = mkState('sensor.ecco_intel_hostile', edge[0].value, hostileAttributes());
  });
  const text = dump(s.rows.map((r) => [r.stateText, r.attributes, r.redacted, r.searchText]));
  const exported = exportRows(s.rows, 'json', { nowMs: NOW }) + exportRows(s.rows, 'csv', { nowMs: NOW });
  for (const e of edge) {
    for (const f of [e.value, e.value.slice(4, 18)]) {
      assert.ok(!text.includes(f), `${e.label} leaked into a row`);
      assert.ok(!exported.includes(f), `${e.label} leaked into the export`);
    }
  }
});

test('AC9 [r1] the age comes from last_updated, never from last_changed: updated just now is live whatever last_changed says; updated long ago is stale', () => {
  const mk = (changedAgeS, updatedAgeS) => ({ entity_id: 'sensor.t', state: '5', attributes: {}, last_changed: isoAt(NOW - changedAgeS * 1000), last_updated: isoAt(NOW - updatedAgeS * 1000) });
  const SRC1 = { id: 'T', stale_after_s: 900 };
  const fresh = classifyRow(SRC1, mk(99999, 10), NOW);
  assert.equal(fresh.status, 'LIVE', 'changed long ago but updated 10 s ago');
  assert.equal(fresh.ageS, 10);
  const old = classifyRow(SRC1, mk(10, 99999), NOW);
  assert.equal(old.status, 'STALE', 'changed just now but last updated long ago (not a state a real hass produces, but the rule is last_updated)');
  assert.equal(old.ageS, 99999);
});

test('AC9 [r1] a timestamp more than a few minutes in the future is UNVERIFIED (clock skew), with no age; a small skew is still age 0 and live', () => {
  const SRC1 = { id: 'T', stale_after_s: 900 };
  const NOLIMIT = { id: 'T', stale_after_s: null };
  const at = (ageS) => ({ entity_id: 'sensor.t', state: '5', attributes: {}, last_changed: isoAt(NOW - ageS * 1000), last_updated: isoAt(NOW - ageS * 1000) });
  for (const [ageS, want] of [[-30, 'LIVE'], [-120, 'LIVE'], [-299, 'LIVE'], [-301, 'UNVERIFIED'], [-3600, 'UNVERIFIED'], [-86400, 'UNVERIFIED']]) {
    for (const src of [SRC1, NOLIMIT]) {
      const r = classifyRow(src, at(ageS), NOW);
      assert.equal(r.status, want, `${ageS} s with ${src.stale_after_s === null ? 'no limit' : 'a limit'}`);
      if (want === 'UNVERIFIED') {
        assert.equal(r.ageS, null, 'no invented age');
        assert.ok(!r.flags.includes('LIVE'));
      } else assert.equal(r.ageS, 0);
    }
  }
  assert.equal(formatAge(classifyRow(SRC1, at(-86400), NOW).ageS), 'age unknown');
});

test('AC9 [r1] a freshness limit of zero is refused by the catalogue validator (it would silently mean "never stale"); null still means not monitored', () => {
  let c = cat();
  c.sources[1].stale_after_s = 0;
  const r = validateCatalogue(c);
  assert.equal(r.ok, false);
  assert.ok(r.errors.some((e) => e.path === 'sources[1].stale_after_s'), dump(r.errors));
  c = cat();
  c.sources[1].stale_after_s = null;
  assert.equal(validateCatalogue(c).ok, true);
  c = cat();
  c.sources[1].stale_after_s = 1;
  assert.equal(validateCatalogue(c).ok, true);
});

test('AC9 [r1] the simulated vocabulary: provenance, data_source and source_kind that name a fixture, mock, demo, sample, fake or dummy are SIMULATED too', () => {
  const st = (a) => ({ entity_id: 'sensor.t', state: '5', attributes: a, last_changed: isoAt(NOW - 5000), last_updated: isoAt(NOW - 5000) });
  for (const w of ['fixture', 'FIXTURE_DATA', 'mock', 'demo', 'sample', 'fake', 'dummy', 'simulation', 'SYNTHETIC_TEST', 'simulated']) {
    for (const k of ['provenance', 'data_source', 'source_kind']) assert.equal(classifyRow({ id: 'T', stale_after_s: null }, st({ [k]: w }), NOW).status, 'SIMULATED', `${k}=${w}`);
  }
  for (const w of ['VERIFIED', 'measured', 'integration', 'sensor', 'prototype']) assert.equal(classifyRow({ id: 'T', stale_after_s: null }, st({ provenance: w }), NOW).status, 'LIVE', w);
});

test('AC11 [r1] CSV keeps a plain number exact (a negative number is not a formula) and still neutralises a real formula', () => {
  const s = snap();
  const base = s.rows.find((r) => r.status === 'LIVE');
  const csv = (state) => exportRows([{ ...base, stateText: state, unitText: '' }], 'csv', { nowMs: NOW }).split('\n')[1];
  for (const n of ['-5', '-0.5', '12', '3.25', '-1e3', '+5', '2.5E-3']) {
    const line = csv(n);
    assert.ok(line.split(',').includes(n), `${n} is exported exactly: ${line}`);
    assert.ok(!line.includes(`'${n}`), `${n} has no apostrophe`);
  }
  for (const f of ['=1+1', '@SUM(1)', '-5+3', '-A1', '+cmd', '=cmd|calc', '-', '--5', '1-5']) {
    const line = csv(f);
    if (/^[=+\-@]/.test(f)) assert.ok(line.includes(`'${f}`), `${f} is neutralised: ${line}`);
  }
});

test('AC12 [r1] row reuse: an unchanged hass constructs no row, one changed entity constructs one row, and the order still equals a fresh build', () => {
  const c = validateCatalogue(cat()).catalogue;
  const states = bigStates(1500);
  const first = buildSnapshot(states, c, NOW);
  assert.ok(Number.isInteger(STATS.rowsBuilt));
  let before = STATS.rowsBuilt;
  const again = buildSnapshot({ ...states }, c, NOW + 400);
  assert.equal(STATS.rowsBuilt - before, 0, 'no row is constructed for objects that did not change');
  assert.deepEqual(again.rows.map((r) => r.key), first.rows.map((r) => r.key));
  const id = 'sensor.ecco_intel_synth_00007';
  const states2 = { ...states, [id]: mkState(id, 'changed', states[id].attributes) };
  before = STATS.rowsBuilt;
  const s2 = buildSnapshot(states2, c, NOW + 400);
  assert.equal(STATS.rowsBuilt - before, 1);
  assert.equal(byEntity(s2, id).stateText, 'changed');
  // a new discovered entity that sorts early moves every later discovered row: the reused rows must carry the new position
  const early = 'sensor.ecco_intel_aaa_first';
  const states3 = { ...states2, [early]: mkState(early, '1', {}) };
  const s3 = buildSnapshot(states3, c, NOW + 400);
  const fresh = buildSnapshot(states3, validateCatalogue(cat()).catalogue, NOW + 400);
  assert.deepEqual(s3.rows.map((r) => r.key), fresh.rows.map((r) => r.key), 'same order as a build with no reuse at all');
  // past the one-second window the age-dependent fields are recomputed
  before = STATS.rowsBuilt;
  const later = buildSnapshot(states3, c, NOW + 5000);
  assert.ok(STATS.rowsBuilt - before >= later.rows.length - 1, 'a later clock rebuilds the rows (ages move)');
  assert.ok(byEntity(later, id).ageS > byEntity(s2, id).ageS);
});

test('AC12 [r1] the snapshot names every entity it reads (sources, discovered entities and alert inputs), so a caller can tell an unrelated update from a relevant one', () => {
  const c = validateCatalogue(cat()).catalogue;
  const s = buildSnapshot(miniStates(), c, NOW);
  assert.ok(Array.isArray(s.watch));
  for (const r of s.rows) assert.ok(s.watch.includes(r.entity_id), r.entity_id);
  for (const a of c.alerts) assert.ok(s.watch.includes(a.entity_id), a.entity_id);
  assert.ok(!s.watch.includes('light.example_lamp'));
});

// ---- alert grammar: not_in and state_outside ----
const withAlerts = (alerts) => {
  const c = cat();
  c.alerts = alerts;
  return validateCatalogue(c);
};
const alertIds = (states, catalogue) => deriveAlerts(buildSnapshot(states, catalogue, NOW), catalogue).map((a) => `${a.severity}:${a.id}`);
const STATUS = 'sensor.ecco_intel_status';

test('AC6 [r1] alert form {attribute, not_in}: validated like the other forms; both in and not_in, an empty list or a non-list is refused', () => {
  const mkAlert = (when) => ({ id: 'N1', severity: 'critical', entity_id: STATUS, when, text: 't', action: 'a' });
  assert.equal(withAlerts([mkAlert({ attribute: 'mode', not_in: ['SHADOW'] })]).ok, true);
  assert.equal(withAlerts([mkAlert({ attribute: 'mode', not_in: ['SHADOW'] })]).catalogue.alerts.length, 1);
  assert.equal(withAlerts([mkAlert({ attribute: 'a', not_in: [true, false, 'x', 3] })]).ok, true, 'booleans, texts and numbers');
  for (const bad of [{ attribute: 'mode', in: ['A'], not_in: ['B'] }, { attribute: 'mode', not_in: [] }, { attribute: 'mode', not_in: 'SHADOW' }, { attribute: '', not_in: ['A'] }, { not_in: ['A'] },
    { attribute: 'mode', not_in: [{}] }, { attribute: 'mode', not_in: [null] }]) {
    const r = withAlerts([mkAlert(bad)]);
    assert.equal(r.ok, false, dump(bad));
    assert.equal(r.catalogue.alerts.length, 0, `${dump(bad)} is dropped, not guessed`);
  }
});

test('AC6 [r1] alert form {attribute, not_in}: fires when the value is not STRICTLY one of the list; an absent attribute or a down entity is "cannot check", never silent and never critical', () => {
  const cc = withAlerts([{ id: 'N1', severity: 'critical', entity_id: STATUS, when: { attribute: 'mode', not_in: ['SHADOW'] }, text: 'mode alert text', action: 'do it' }]).catalogue;
  const run = (mutate) => alertIds(miniStates(mutate), cc);
  assert.deepEqual(run((s) => { s[STATUS].attributes.mode = 'SHADOW'; }), []);
  assert.deepEqual(run((s) => { s[STATUS].attributes.mode = 'ASSISTED'; }), ['critical:N1']);
  assert.deepEqual(run((s) => { s[STATUS].attributes.mode = 'shadow'; }), ['critical:N1'], 'no case folding: SHADOW is the one word');
  assert.deepEqual(run((s) => { s[STATUS].attributes.mode = ''; }), ['critical:N1']);
  assert.deepEqual(run((s) => { s[STATUS].attributes.mode = { x: 1 }; }), ['critical:N1']);
  assert.deepEqual(run((s) => { delete s[STATUS].attributes.mode; }), ['warning:N1:unverifiable']);
  assert.deepEqual(run((s) => { s[STATUS].attributes.mode = null; }), ['warning:N1:unverifiable']);
  assert.deepEqual(run((s) => { s[STATUS].state = 'unavailable'; }), ['warning:N1:unverifiable']);
  assert.deepEqual(run((s) => { delete s[STATUS]; }), ['warning:N1:unverifiable']);
  const strict = withAlerts([{ id: 'N2', severity: 'critical', entity_id: STATUS, when: { attribute: 'applies_nothing', not_in: [true] }, text: 't', action: 'a' }]).catalogue;
  const runs = (v) => alertIds(miniStates((s) => { s[STATUS].attributes.applies_nothing = v; }), strict);
  assert.deepEqual(runs(true), []);
  for (const v of [false, 0, 1, 'true', 'True', 'yes', 'no', '', [true]]) assert.deepEqual(runs(v), ['critical:N2'], `${JSON.stringify(v)} is not strictly true`);
});

test('AC6 [r1] alert form {state_outside}: fires for a state that is not listed; an unavailable, unknown or missing entity is "cannot check" (another alert says it is down)', () => {
  const mkAlert = (when) => ({ id: 'O1', severity: 'warning', entity_id: STATUS, when, text: 'status unknown to this view', action: 'a' });
  assert.equal(withAlerts([mkAlert({ state_outside: ['OK', 'STALE'] })]).ok, true);
  for (const bad of [{ state_outside: [] }, { state_outside: 'OK' }, { state_outside: [1] }, { state_outside: ['OK'], state_in: ['x'] }]) {
    const r = withAlerts([mkAlert(bad)]);
    if (bad.state_in) assert.equal(r.catalogue.alerts.length, 1, 'the first form wins, as for the other forms');
    else assert.equal(r.ok, false, dump(bad));
  }
  const cc = withAlerts([mkAlert({ state_outside: ['OK', 'STALE'] })]).catalogue;
  const run = (mutate) => alertIds(miniStates(mutate), cc);
  assert.deepEqual(run((s) => { s[STATUS].state = 'OK'; }), []);
  assert.deepEqual(run((s) => { s[STATUS].state = 'STALE'; }), []);
  assert.deepEqual(run((s) => { s[STATUS].state = 'WEIRD'; }), ['warning:O1']);
  assert.deepEqual(run((s) => { s[STATUS].state = 'ok'; }), ['warning:O1'], 'no case folding');
  assert.deepEqual(run((s) => { s[STATUS].state = 'unavailable'; }), ['warning:O1:unverifiable']);
  assert.deepEqual(run((s) => { s[STATUS].state = 'unknown'; }), ['warning:O1:unverifiable']);
  assert.deepEqual(run((s) => { delete s[STATUS]; }), ['warning:O1:unverifiable']);
});

// ---- the child-card guard is an allowlist ----
const ALLOWED_MINIMAL = {
  markdown: { type: 'markdown', content: 'x' }, entities: { type: 'entities', entities: ['sensor.x'] }, glance: { type: 'glance', entities: ['sensor.x'] },
  'history-graph': { type: 'history-graph', entities: ['sensor.x'] }, 'statistics-graph': { type: 'statistics-graph', entities: ['sensor.x'] },
  sensor: { type: 'sensor', entity: 'sensor.x' }, gauge: { type: 'gauge', entity: 'sensor.x' }, entity: { type: 'entity', entity: 'sensor.x' },
  heading: { type: 'heading', heading: 'x' }, 'vertical-stack': { type: 'vertical-stack', cards: [{ type: 'markdown', content: 'x' }] },
  'horizontal-stack': { type: 'horizontal-stack', cards: [{ type: 'markdown', content: 'x' }] }, grid: { type: 'grid', cards: [{ type: 'markdown', content: 'x' }] },
  conditional: { type: 'conditional', conditions: [], card: { type: 'markdown', content: 'x' } }, tile: { type: 'tile', entity: 'sensor.x' },
};

test('AC16 [r1] validateChildCards: only an ALLOWLIST of card types may sit in a Geek-visible region (the read-only built-in cards and the ECCO Intelligence card)', () => {
  for (const [t, cfg] of Object.entries(ALLOWED_MINIMAL)) assert.equal(validateChildCards([cfg]).ok, true, t);
  assert.equal(validateChildCards([{ type: 'custom:ecco-intelligence-card', entities: { status: 'sensor.x' } }]).ok, true, 'the read-only Intelligence card is on the default list');
  for (const t of ['picture-glance', 'area', 'picture-entity', 'picture-elements', 'map', 'weather-forecast', 'logbook', 'calendar', 'markdown-but-not', 'light', 'button', 'media-control', 'iframe']) {
    const r = validateChildCards([{ type: t, entities: ['sensor.x'], entity: 'sensor.x', area: 'kitchen', image: 'x' }]);
    assert.equal(r.ok, false, t);
    assert.ok(r.errors.some((e) => /not on the list|allowed|can write/.test(e.message)), `${t}: ${dump(r.errors)}`);
  }
});

test('AC16 [r1] validateChildCards: a custom card is refused unless it is on the default list or named in allowCustom; the allowance accepts only well-formed custom names', () => {
  const btn = { type: 'custom:button-card', entity: 'sensor.x' };
  for (const name of ['custom:button-card', 'custom:mushroom-entity-card', 'custom:some-other-card', 'custom:ecco-tou-settings-card']) {
    assert.equal(validateChildCards([{ type: name, entity: 'sensor.x' }]).ok, false, name);
  }
  assert.equal(validateChildCards([btn], { allowCustom: ['custom:button-card'] }).ok, true, 'the dashboard author names it');
  assert.equal(validateChildCards([btn], { allowCustom: ['custom:other-card'] }).ok, false);
  for (const bad of [['button-card'], ['custom:Button-Card'], ['custom:'], ['custom:x'], [5], [null], 'custom:button-card', undefined, null, {}]) {
    assert.equal(validateChildCards([btn], { allowCustom: bad }).ok, false, `allowCustom ${dump(bad)} allows nothing`);
  }
  // an allowed custom card still passes through the action rules
  assert.equal(validateChildCards([{ ...btn, tap_action: { action: 'toggle' } }], { allowCustom: ['custom:button-card'] }).ok, false);
});

test('AC16 [r1] validateChildCards: the allowlist applies inside stacks, grids and conditionals, and to the header and footer of a card', () => {
  const pg = { type: 'picture-glance', entities: ['sensor.x'], image: 'x' };
  const btn = { type: 'custom:button-card', entity: 'sensor.x' };
  for (const wrap of [(c) => ({ type: 'vertical-stack', cards: [c] }), (c) => ({ type: 'horizontal-stack', cards: [{ type: 'markdown' }, c] }), (c) => ({ type: 'grid', cards: [c] }),
    (c) => ({ type: 'conditional', conditions: [], card: c }), (c) => ({ type: 'vertical-stack', cards: [{ type: 'horizontal-stack', cards: [c] }] })]) {
    assert.equal(validateChildCards([wrap(pg)]).ok, false, 'picture-glance inside a container');
    assert.equal(validateChildCards([wrap(btn)]).ok, false, 'a custom card inside a container');
    assert.equal(validateChildCards([wrap({ type: 'markdown', content: 'x' })]).ok, true);
  }
  const base = { type: 'entities', entities: ['sensor.x'] };
  assert.equal(validateChildCards([{ ...base, footer: { type: 'buttons', entities: [{ entity: 'light.x' }] } }]).ok, false, 'a buttons footer toggles by default');
  assert.equal(validateChildCards([{ ...base, header: { type: 'picture', image: 'x' } }]).ok, true);
  assert.equal(validateChildCards([{ ...base, footer: { type: 'graph', entity: 'sensor.x' } }]).ok, true);
  assert.equal(validateChildCards([{ ...base, footer: { type: 'widgets', entities: [] } }]).ok, false);
});

test('AC16 [r1] validateChildCards: a heading badge on a writable entity must state a safe tap_action; a read-only badge needs nothing', () => {
  const heading = (badge) => ({ type: 'heading', heading: 'x', badges: [badge] });
  assert.equal(validateChildCards([heading({ type: 'entity', entity: 'sensor.x' })]).ok, true);
  assert.equal(validateChildCards([heading({ type: 'entity', entity: 'input_boolean.x' })]).ok, false);
  assert.equal(validateChildCards([heading({ type: 'entity', entity: 'input_boolean.x', tap_action: { action: 'toggle' } })]).ok, false);
  assert.equal(validateChildCards([heading({ type: 'entity', entity: 'input_boolean.x', tap_action: { action: 'more-info' } })]).ok, true);
  assert.equal(validateChildCards([heading({ type: 'entity', entity: 'input_boolean.x', tap_action: { action: 'none' } })]).ok, true);
});

test('AC16 [r1] validateConfig: allow_custom_cards is a list of well-formed custom card names; a bad entry is reported and ignored', () => {
  assert.deepEqual(validateConfig({ allow_custom_cards: ['custom:button-card', 'custom:foo-card'] }).allowCustom, ['custom:button-card', 'custom:foo-card']);
  assert.deepEqual(validateConfig({}).allowCustom, []);
  assert.deepEqual(validateConfig({}).errors, []);
  const r = validateConfig({ allow_custom_cards: ['custom:ok-card', 'bad', 5, 'custom:Bad-Card'] });
  assert.deepEqual(r.allowCustom, ['custom:ok-card']);
  assert.ok(r.errors.length >= 1 && r.errors.every((e) => e.path.startsWith('allow_custom_cards')));
  assert.equal(validateConfig({ allow_custom_cards: 'custom:x-y' }).errors.length, 1);
  assert.deepEqual(validateConfig({ allow_custom_cards: 'custom:x-y' }).allowCustom, []);
});

test('AC12 [r1] a long attribute VALUE is cut at LIMITS.value in the row, with a marker that says how much was dropped (the row cap, not only the larger keep cap)', () => {
  assert.equal(LIMITS.value, 300);
  const s = snap((states) => {
    states['sensor.ecco_intel_new_diagnostic'].attributes.long_text = 'y'.repeat(1000);
    states['sensor.ecco_intel_new_diagnostic'].attributes.exact_text = 'z'.repeat(LIMITS.value);
  });
  const r = byEntity(s, 'sensor.ecco_intel_new_diagnostic');
  const a = r.attributes.find((x) => x.path === 'long_text');
  assert.ok(a.value.startsWith('y'.repeat(LIMITS.value)));
  assert.ok(!a.value.includes('y'.repeat(LIMITS.value + 1)), 'nothing beyond the cap is shown');
  assert.match(a.value, /\[truncated 700 more characters\]$/);
  assert.equal(a.truncated, true);
  const e = r.attributes.find((x) => x.path === 'exact_text');
  assert.equal(e.value, 'z'.repeat(LIMITS.value), 'a value exactly at the cap is untouched');
  assert.equal(e.truncated, false);
});

// ---------------------------------------------------------------------------------------------------------------------------
// Review round 2 ([r2]): each test below was written to FAIL on the card as reviewed (or on the mutant the reviewer named) and to pass with its fix
// ---------------------------------------------------------------------------------------------------------------------------
test('AC12 [r2] the snapshot also names the entity of an alert that is not a source (reviewer probe P8, mutant R2-36): an update of that entity is relevant to the view', () => {
  const c = cat();
  c.alerts = [...c.alerts, { id: 'A90', severity: 'critical', entity_id: 'sensor.zz_outside_probe', when: { state_in: ['bad'] }, text: 'The outside probe says bad.', action: 'Check the outside probe.' }];
  const v = validateCatalogue(c);
  assert.equal(v.ok, true);
  const s = buildSnapshot(miniStates(), v.catalogue, NOW);
  assert.ok(s.watch.includes('sensor.zz_outside_probe'), 'watched');
  assert.ok(!s.rows.some((r) => r.entity_id === 'sensor.zz_outside_probe'), 'not a row: only the strip reads it');
  assert.ok(Object.keys(s.alertInputs).includes('sensor.zz_outside_probe'));
  const states = miniStates();
  states['sensor.zz_outside_probe'] = mkState('sensor.zz_outside_probe', 'bad', {});
  assert.ok(deriveAlerts(buildSnapshot(states, v.catalogue, NOW), v.catalogue).some((a) => a.id === 'A90'));
});

test('AC9 [r2] a row reused within the window is re-classified: built just before stale_after_s it turns STALE on time, not up to a second late', () => {
  const c = validateCatalogue(cat()).catalogue;
  const id = 'sensor.ecco_intel_status';
  const src = c.sources.find((s) => s.entity_id === id);
  assert.equal(src.stale_after_s, 900);
  const states = miniStates();
  states[id] = mkState(id, 'OK', states[id].attributes, { ageS: 899.6 });
  assert.equal(row(buildSnapshot(states, c, NOW), 'S01').status, 'LIVE', 'at its own clock the row is live');
  const before = STATS.rowsBuilt;
  const later = buildSnapshot({ ...states }, c, NOW + 900);
  assert.equal(row(later, 'S01').status, 'STALE', 'a row reused for a second would still say Live');
  assert.ok(row(later, 'S01').ageS > 900);
  assert.equal(STATS.rowsBuilt - before, 1, 'only that row was rebuilt: the others, far from their limits, are still reused');
});

test('AC9 [r2] at every offset inside the reuse window a row carries the status a fresh classification gives (around the stale limit and around the clock-skew limit)', () => {
  const c = validateCatalogue(cat()).catalogue;
  const id = 'sensor.ecco_intel_status';
  const src = c.sources.find((s) => s.entity_id === id);
  // an age is how long ago the state was updated: negative is a timestamp ahead of the browser clock (FUTURE_SKEW_MS is 300 s)
  for (const age of [898.5, 899.0, 899.5, 899.9, 900.0, 900.4, -299.5, -300.0, -300.4, -300.5, -301]) {
    for (const d of [0, 100, 500, 900, 999]) {
      const st = miniStates();
      st[id] = mkState(id, 'OK', st[id].attributes, { ageS: age });
      buildSnapshot(st, c, NOW); // prime the reuse
      const r = row(buildSnapshot({ ...st }, c, NOW + d), 'S01');
      const fresh = classifyRow(src, st[id], NOW + d);
      assert.equal(r.status, fresh.status, `age ${age} s, +${d} ms`);
      assert.deepEqual(r.flags, fresh.flags, `age ${age} s, +${d} ms`);
    }
  }
  // and the two cases that matter are really different statuses at the two ends of the window (so the loop above proves something)
  const ahead = miniStates();
  ahead[id] = mkState(id, 'OK', ahead[id].attributes, { ageS: -300.5 });
  assert.equal(classifyRow(src, ahead[id], NOW).status, 'UNVERIFIED');
  assert.equal(classifyRow(src, ahead[id], NOW + 900).status, 'LIVE');
  assert.equal(row(buildSnapshot({ ...ahead }, c, NOW), 'S01').status, 'UNVERIFIED');
  assert.equal(row(buildSnapshot({ ...ahead }, c, NOW + 900), 'S01').status, 'LIVE', 'the skew ended inside the window: not Unverified for another second');
});

test('AC12 [r2] a reused row is not reused for ever: the same catalogue and the same state objects, read five seconds later, give the later age (the window is what keeps ages moving)', () => {
  // the older round-1 test builds with a second catalogue object in between, which rebuilds every row by itself; this one keeps the catalogue and the states
  const c = validateCatalogue(cat()).catalogue;
  const states = miniStates();
  const first = buildSnapshot(states, c, NOW);
  const before = STATS.rowsBuilt;
  const same = buildSnapshot({ ...states }, c, NOW + 200);
  assert.equal(STATS.rowsBuilt - before, 0, 'inside the window every row is reused');
  const later = buildSnapshot({ ...states }, c, NOW + 5000);
  const aged = first.rows.filter((r) => r.ageS !== null);
  assert.ok(aged.length >= 10, 'most rows have an age');
  for (const r of aged) {
    const l = later.rows.find((x) => x.key === r.key);
    assert.ok(Math.abs(l.ageS - r.ageS - 5) < 0.01, `${r.key}: ${r.ageS} -> ${l.ageS}`);
    assert.equal(same.rows.find((x) => x.key === r.key).ageS, r.ageS, 'a reused row keeps its built age inside the window');
  }
  assert.ok(STATS.rowsBuilt - before >= aged.length, 'past the window the rows are built again');
});

test('AC10 [r2] a webhook is withheld wherever it sits, under an innocent key too (the id in its path is the credential); ordinary paths and words are not (reviewer probe P11)', () => {
  const j = (...p) => p.join('');
  const secrets = [j('https://hooks.example.test/api/', 'web', 'hook/', 'abcdef123456'), j('/api/', 'web', 'hook/', 'q1w2e3r4t5y6'),
    j('POST ', '/api/', 'web', 'hook/', 'abcdef-1234_xyz', ' failed'), j('hooks.example.test/', 'services/', 'T00000000/B00000000/abcdefghijkl'),
    // this form has no digit and no capital, so no blob rule helps: only the webhook rule can withhold it (the mutant that drops the services form shows it)
    j('hooks.example.test/', 'services/', 'team-alpha/chan-beta/abcdefghijkl'), j('https://HOOKS.EXAMPLE.TEST/API/', 'WEB', 'HOOK/', 'ABCDEF123456')];
  for (const v of secrets) {
    assert.equal(redactValue(v, { key: 'note' }), WITHHELD, v);
    assert.equal(redactValue({ info: { deep: [v] } }).info.deep[0], WITHHELD, `nested: ${v}`);
    assert.equal(redactAttributes({ friendly_name: 'Probe', last_call: v }).last_call, WITHHELD, `attribute: ${v}`);
  }
  for (const v of ['/api/states/sensor.example', j('/api/', 'web', 'hook/', 'short'), 'the webhook is off', 'hooks.example.test/docs/page', j('hooks.example.test/', 'services/', 'short'), 'a long path /api/config/core']) {
    assert.notEqual(redactValue(v, { key: 'note' }), WITHHELD, v);
  }
});

test('AC10 [r2] a key that ends in user or login after a qualifier is withheld (mqtt_user, db_login, serviceUser); a bare user, a lone login word and unrelated keys are shown (reviewer probe P11)', () => {
  const red = redactAttributes({
    mqtt_user: 'svc-account', db_login: 'svc-db', serviceUser: 'svc-one', 'ha-login': 'svc-two', sftp_users: ['svc-a', 'svc-b'], MQTT_USER: 'svc-three',
    user: 'visible-user', login: 'visible-login', user_count: 3, userland: 'visible-land', logins_today: 7, friendly_name: 'Probe',
  });
  for (const k of ['mqtt_user', 'db_login', 'serviceUser', 'ha-login', 'sftp_users', 'MQTT_USER']) assert.equal(red[k], WITHHELD, k);
  assert.deepEqual([red.user, red.login, red.user_count, red.userland, red.logins_today, red.friendly_name], ['visible-user', 'visible-login', 3, 'visible-land', 7, 'Probe']);
  assert.ok(!JSON.stringify(red).includes('svc-'), 'none of the account names is anywhere in the result');
});

test('AC10 [r2] the webhook values and the login keys hold on every path: row text, raw attributes, the search index and the export carry none of them', () => {
  const hooks = SECRET_VALUES.slice(32);
  assert.equal(hooks.length, 3, 'three round-two webhook values');
  assert.ok(SECRET_KEYS.slice(-5).every((k) => /user|login/i.test(k)), 'and the last five hostile keys are the login names');
  const s = snap((states) => {
    states['sensor.ecco_intel_hostile'] = mkState('sensor.ecco_intel_hostile', hooks[0].value, hostileAttributes());
  });
  const text = dump(s.rows.map((r) => [r.stateText, r.attributes, r.redacted, r.searchText]));
  const exported = exportRows(s.rows, 'json', { nowMs: NOW }) + exportRows(s.rows, 'csv', { nowMs: NOW });
  for (const h of hooks) {
    for (const f of [h.value, h.value.slice(4, 18)]) {
      assert.ok(!text.includes(f), `${h.label} leaked into a row`);
      assert.ok(!exported.includes(f), `${h.label} leaked into the export`);
    }
  }
  for (const k of SECRET_KEYS.slice(-5)) {
    assert.ok(!text.includes(KEY_MARKER(k)) && !exported.includes(KEY_MARKER(k)), `${k}: its value leaked`);
  }
});

// ---------------------------------------------------------------------------------------------------------------------------
// Review round 3 ([r3])
// ---------------------------------------------------------------------------------------------------------------------------
// R3-20: a mutant that read a state_not_in list literally survived every suite, because the one catalogue alert that uses state_not_in (A04) lists neither
// `unknown` nor `unavailable`. The reading is FAIL-SAFE: an entity that is down (missing, unavailable or unknown) fires the alert, whatever the list says
// ("alert when the state is not one of these" cannot be answered for a source that is not publishing, and silence would be the wrong answer). A catalogue that
// lists `unknown` or `unavailable` in state_not_in does not get a quiet strip for a down entity. The Intelligence catalogue has no state_not_in alert, so this
// matters when the shell is reused on another tab.
test('AC6 [r3] state_not_in is fail-safe: a down entity (missing, unavailable, unknown) fires the alert even when the list itself names unknown or unavailable', () => {
  const listed = () => {
    const c = cat();
    const a04 = c.alerts.find((a) => a.id === 'A04');
    assert.ok(Array.isArray(a04.when.state_not_in));
    a04.when.state_not_in.push('unknown', 'unavailable');
    return c;
  };
  const fires = (mutate, c) => alertsFor(mutate, c).some((x) => x.id === 'A04' && x.kind === 'condition');
  for (const state of ['unknown', 'unavailable']) {
    assert.equal(fires((s) => { s['sensor.ecco_intel_status'].state = state; }, listed()), true, `${state}, listed: the alert fires`);
    assert.equal(fires((s) => { s['sensor.ecco_intel_status'].state = state; }), true, `${state}, not listed: the alert fires`);
  }
  assert.equal(fires((s) => { delete s['sensor.ecco_intel_status']; }, listed()), true, 'missing, listed: the alert fires');
  assert.equal(fires((s) => { delete s['sensor.ecco_intel_status']; }), true, 'missing, not listed: the alert fires');
  // an entity that is up reads the list as written
  assert.equal(fires((s) => { s['sensor.ecco_intel_status'].state = 'STARTING'; }, listed()), false, 'a listed state of an entity that is up is quiet');
  assert.equal(fires((s) => { s['sensor.ecco_intel_status'].state = 'OK'; }), false);
  assert.equal(fires((s) => { s['sensor.ecco_intel_status'].state = 'SOMETHING_NEW'; }, listed()), true, 'an unlisted state of an entity that is up fires');
});

test('AC10 [r3] every round-three value is withheld under an innocent key, nested in a list and on its own', () => {
  assert.ok(SECRET_VALUES_R3.length >= 12);
  for (const s of SECRET_VALUES_R3) {
    assert.equal(redactValue(s.value, { key: 'note' }), WITHHELD, s.label);
    assert.equal(redactValue({ any: [s.value] }).any[0], WITHHELD, `${s.label} nested in a list`);
    assert.equal(redactValue(s.value), WITHHELD, `${s.label} with no key`);
  }
});

test('AC10 [r3] a short password word after a qualifier, pw in any position and the compact forms withhold their value; a bare pass and unrelated words stay visible (reviewer probe)', () => {
  const out = redactAttributes(Object.fromEntries(SECRET_KEYS_R3.map((k) => [k, KEY_MARKER(k)])));
  for (const k of SECRET_KEYS_R3) assert.equal(out[k], WITHHELD, k);
  const shown = { pass: 'visible-pass', passed: 'visible-passed', pass_count: 3, compass: 'visible-compass', bypass_mode: 'visible-bypass', overpass: 'visible-over',
    pwr: 'visible-pwr', pass_through: 'visible-through', self_test: 'pass', pass_rate: 0.5, friendly_name: 'Probe' };
  const red = redactAttributes(shown);
  assert.deepEqual(red, shown, 'none of these is a password name: a bare pass is also a test result, and the others only contain the letters');
  assert.ok(!JSON.stringify(redactAttributes({ x_pass: 'zq7-1', Y_PW: 'zq7-2', 'a-b-pass': 'zq7-3' })).includes('zq7'));
});

test('AC10 [r3] the new value rules do not take look-alikes for secrets: a version, a plain number, a short revision under a revision key, prose with the word pass, a coarse pair', () => {
  const look = {
    version: '2026.1114.0900', digits12: '123456789012', hex11: 'aabbccddeef', hex13: 'aabbccddeeff1', sentence: 'the self-test pass: true today', passed: 'pass: ok',
    ratio: '0.125', coarse: '51.5, -0.1', one_decimal_pair: '1.5, 2.5', mixed_pair: '1.250, 3.5', dotted_words: 'abcd.efgh.ijkl', build: 'version 1.2.3',
    wifi_word: 'wifi: connected', wifi_note: 'the wifi name', passwordless: 'no password needed', field_note: 'the pw field is empty',
  };
  const red = redactAttributes(look);
  for (const [k, v] of Object.entries(look)) assert.equal(red[k], v, `${k}: ${v} is not a secret`);
  // a short git revision is a public value under a revision key and a MAC-shaped secret anywhere else
  assert.equal(redactValue('1a2b3c4d5e6f', { key: 'git_sha' }), '1a2b3c4d5e6f');
  assert.equal(redactValue('1a2b3c4d5e6f', { key: 'commit' }), '1a2b3c4d5e6f');
  assert.equal(redactValue('1a2b3c4d5e6f', { key: 'note' }), WITHHELD);
  assert.equal(redactValue('  1a2b3c4d5e6f  ', { key: 'note' }), WITHHELD, 'white space around it does not hide it');
  assert.equal(redactValue('AABBCCDDEEFF', { key: 'note' }), WITHHELD, 'upper case');
});

test('AC10 [r3] the round-three values and keys hold on every path: row text, raw attributes, the search index and the export carry none of them', () => {
  const s = snap((states) => {
    states['sensor.ecco_intel_hostile'] = mkState('sensor.ecco_intel_hostile', SECRET_VALUES_R3[0].value, hostileAttributes());
  });
  const text = dump(s.rows.map((r) => [r.stateText, r.attributes, r.redacted, r.searchText]));
  const exported = exportRows(s.rows, 'json', { nowMs: NOW }) + exportRows(s.rows, 'csv', { nowMs: NOW });
  for (const v of SECRET_VALUES_R3) {
    for (const f of [v.value, v.value.slice(2, 12)]) {
      assert.ok(!text.includes(f), `${v.label} leaked into a row`);
      assert.ok(!exported.includes(f), `${v.label} leaked into the export`);
    }
  }
  for (const k of SECRET_KEYS_R3) assert.ok(!text.includes(KEY_MARKER(k)) && !exported.includes(KEY_MARKER(k)), `${k}: its value leaked`);
  assert.equal(searchRows(s.rows, 'hunter22').length, 0, 'the search index holds no password text');
});

// Review round 4 ([r4]): a MAC address written with spaces between the six bytes (reviewer probe: shown)
test('AC10 [r4] a MAC address written with spaces is withheld under an innocent key, nested in a list, on its own and inside a sentence', () => {
  assert.ok(SECRET_VALUES_R4.length >= 3);
  for (const s of SECRET_VALUES_R4) {
    assert.equal(redactValue(s.value, { key: 'note' }), WITHHELD, s.label);
    assert.equal(redactValue({ any: [s.value] }).any[0], WITHHELD, `${s.label} nested in a list`);
    assert.equal(redactValue(s.value), WITHHELD, `${s.label} with no key`);
  }
  assert.equal(redactValue('  aa bb cc dd ee ff  ', { key: 'note' }), WITHHELD, 'white space around it does not hide it');
  assert.equal(redactValue('AA BB CC DD EE FF 11 22', { key: 'note' }), WITHHELD, 'a longer run of bytes contains one');
  assert.equal(redactValue('aa bb cc dd ee ff', { key: 'git_sha' }), WITHHELD, 'a revision key does not excuse a spaced MAC (a revision has no spaces)');
});

test('AC10 [r4] the spaced-MAC rule takes no look-alike for one: six numbers, five or seven-digit groups, a run of the wrong length, a version, prose', () => {
  const look = {
    six_numbers: '10 20 30 40 50 60', six_numbers_b: '12 34 56 78 90 12', five_bytes: 'aa bb cc dd ee', one_digit_end: 'aa bb cc dd ee f', three_digit_start: '1aa bb cc dd ee ff',
    three_digit_end: 'aa bb cc dd ee fff', four_char_groups: 'aabb ccdd eeff', words: 'a bad cab fed bee dad', version: 'version 2026 11 14 09 00 00', hours: 'at 10 11 12 13 14 15 hours',
    sentence: 'the strip was clear for six days in a row',
  };
  const red = redactAttributes(look);
  for (const [k, v] of Object.entries(look)) assert.equal(red[k], v, `${k}: ${v} is not a MAC address`);
});

test('AC10 [r4] the spaced MAC addresses hold on every path: row text, raw attributes, the search index and the export carry none of them', () => {
  const s = snap((states) => {
    states['sensor.ecco_intel_hostile'] = mkState('sensor.ecco_intel_hostile', SECRET_VALUES_R4[0].value, hostileAttributes());
  });
  const text = dump(s.rows.map((r) => [r.stateText, r.attributes, r.redacted, r.searchText]));
  const exported = exportRows(s.rows, 'json', { nowMs: NOW }) + exportRows(s.rows, 'csv', { nowMs: NOW });
  for (const v of SECRET_VALUES_R4) {
    for (const f of [v.value, v.value.slice(2, 14)]) {
      assert.ok(!text.includes(f), `${v.label} leaked into a row`);
      assert.ok(!exported.includes(f), `${v.label} leaked into the export`);
    }
  }
});
