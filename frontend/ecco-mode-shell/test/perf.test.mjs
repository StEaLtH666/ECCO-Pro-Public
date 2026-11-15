// Review round 7 ([r7]): THE PERFORMANCE CLASS of the redactor. Round 6 made the card read a string whole, up to 20000 characters, and three of the value rules were quadratic on a text that only LOOKS like
// the start of one of them: one entity with 200 attributes of a 19990-character near-miss text kept the main thread, and with it the alert strip, busy for 38 seconds on every update of that entity. The
// round-6 tests named three texts and passed; the class is "any rule is more than linear in the length of the text it reads, on ANY text", so these tests run EVERY rule alone (no gate, no pre-test: the worst
// case, a text that opens every gate) and the whole read, on a family of near-miss texts of 10000 and 20000 characters (and, where the work is measurable, of 40000), and assert BOTH an absolute generous
// bound AND that the time grows linearly (time at 20000 divided by time at 10000 below 3.5, the minimum of several runs, re-measured once before a failure is reported), so a quadratic rule fails on any machine,
// fast or slow. Then the whole entity: the reviewer's probe (200 attributes of 19990 characters), and the scan budget that bounds an entity whatever its shape.
// These tests are slow-ish (several seconds), so the mutation runner gives this file only to the mutants that are about speed (`perf: true`).
import test from 'node:test';
import assert from 'node:assert/strict';
import { loadCard, miniCatalogue, miniStates, mkState, NOW } from './helpers.mjs';
import { UNITS, textOf } from './near-miss.mjs';

const core = await loadCard('perf7');
const { WITHHELD, LIMITS, SCAN_RULES, redactValue, redactAttributes, buildSnapshot, validateCatalogue, exportRows } = core;

/** The least time of a call, in milliseconds, over a few trials; a call that is very fast is repeated, so the timer's resolution cannot hide how it grows. */
function leastMs(fn, { trials = 3, floorMs = 2, maxReps = 300 } = {}) {
  fn();
  let t0 = performance.now();
  fn();
  const one = performance.now() - t0;
  const reps = one >= floorMs ? 1 : Math.min(maxReps, Math.max(1, Math.ceil(floorMs / Math.max(one, 0.003))));
  let least = Infinity;
  for (let k = 0; k < trials; k += 1) {
    t0 = performance.now();
    for (let r = 0; r < reps; r += 1) fn();
    least = Math.min(least, (performance.now() - t0) / reps);
  }
  return least;
}

const ABS_RULE_MS = 60; // one rule, one text of 20000 characters: the slowest measured is about 6 ms; a quadratic rule is 100 to 400
const ABS_READ_MS = 100; // the whole read of one text of 20000 characters
const GROWTH = 3.5; // time at twice the length: linear is 2, quadratic is 4 and more

/** Time `run(n)` at 10000 and 20000 characters; fail on the absolute bound; on growth, look again (more trials) before saying so. */
function check(label, run, abs) {
  const t10 = leastMs(() => run(10000), { trials: 2, floorMs: 1 });
  const t20 = leastMs(() => run(20000), { trials: 2, floorMs: 1 });
  assert.ok(t20 <= abs, `${label}: ${t20.toFixed(2)} ms for 20000 characters (bound ${abs} ms)`);
  let ratio = t20 / Math.max(t10, 1e-6);
  if (ratio > GROWTH && t20 > 0.05) {
    const a = leastMs(() => run(10000), { trials: 7 });
    const b = leastMs(() => run(20000), { trials: 7 });
    ratio = b / Math.max(a, 1e-6);
  }
  assert.ok(ratio <= GROWTH || t20 <= 0.05, `${label}: grows by ${ratio.toFixed(2)} for twice the length (${t10.toFixed(3)} ms to ${t20.toFixed(3)} ms): not linear`);
  return { t10, t20, ratio };
}

test('AC12 [r7] the table of rules is the one the card scans with: 23 rules, each with a reason, a gate or null, a pattern, and a pre-test or null; the near-miss family is wide enough to mean something', () => {
  assert.equal(SCAN_RULES.length, 23);
  assert.ok(Object.isFrozen(SCAN_RULES));
  for (const r of SCAN_RULES) {
    assert.equal(typeof r.reason, 'string');
    assert.ok(r.gate === null || typeof r.gate === 'string');
    assert.ok(r.pattern instanceof RegExp);
    assert.ok(r.pretest === null || r.pretest instanceof RegExp);
    assert.equal(r.pattern.global || r.pattern.sticky, false, `${r.reason}: a stateless pattern`);
  }
  assert.equal(new Set(SCAN_RULES.map((r) => r.reason)).size, 23, 'every reason once');
  assert.ok(UNITS.length >= 100, `${UNITS.length} units`);
  for (const u of UNITS) assert.equal(textOf(u, 20000).length, 20000);
});

test('AC12 [r7] EVERY rule alone (no gate, no pre-test) is linear on every near-miss text: under an absolute bound at 20000 characters, and time at 20000 over time at 10000 under 3.5', () => {
  const worst = { ms: 0, label: '' };
  let growth = 0;
  let measured = 0;
  for (const unit of UNITS) {
    const texts = new Map([[10000, textOf(unit, 10000)], [20000, textOf(unit, 20000)]]);
    for (const rule of SCAN_RULES) {
      const re = rule.pattern;
      const r = check(`${rule.reason} on ${JSON.stringify(unit)} repeated`, (n) => re.test(texts.get(n)), ABS_RULE_MS);
      measured += 1;
      if (r.t20 > worst.ms) {
        worst.ms = r.t20;
        worst.label = `${rule.reason} on ${JSON.stringify(unit)}`;
      }
      if (r.t20 > 0.3) growth = Math.max(growth, r.ratio);
    }
  }
  assert.equal(measured, UNITS.length * 23);
  assert.ok(worst.ms < ABS_RULE_MS, `${worst.label}: ${worst.ms.toFixed(2)} ms`);
  console.log(`rules alone: ${measured} measurements; the slowest is ${worst.label} at ${worst.ms.toFixed(2)} ms for 20000 characters; the largest growth of a rule above 0.3 ms is ${growth.toFixed(2)}`);
});

test('AC12 [r7] the amplified check: a rule that takes measurable time on a text is also linear from 20000 to 80000 characters (a pattern is not bounded by the scan bound, so a quadratic one shows here at 16 times, not 4)', () => {
  let n = 0;
  for (const unit of UNITS) {
    const t20 = textOf(unit, 20000);
    for (const rule of SCAN_RULES) {
      const re = rule.pattern;
      const a = leastMs(() => re.test(t20), { trials: 2 });
      if (a < 0.15) continue;
      const t80 = textOf(unit, 80000);
      const b = leastMs(() => re.test(t80), { trials: 3 });
      n += 1;
      let ratio = b / a;
      if (ratio > 7) ratio = leastMs(() => re.test(t80), { trials: 7 }) / leastMs(() => re.test(t20), { trials: 7 });
      assert.ok(ratio <= 7, `${rule.reason} on ${JSON.stringify(unit)}: ${a.toFixed(2)} ms at 20000 and ${b.toFixed(2)} ms at 80000 (x${ratio.toFixed(1)} for four times the length)`);
      assert.ok(b <= 4 * ABS_RULE_MS, `${rule.reason} on ${JSON.stringify(unit)}: ${b.toFixed(1)} ms at 80000 characters`);
    }
  }
  assert.ok(n >= 5, `${n} amplified measurements (the family has texts that take measurable time)`);
});

test('AC12 [r7] the WHOLE read (gates open, every pre-test passed, the tail rules too) is linear on every near-miss text: redactValue of 10000 and of 20000 characters, bare and under a key', () => {
  // an opener that passes every gate and every pre-test and matches no rule
  const opener = ' @ . : ; = / - ? # + pass= eyJ ';
  assert.notEqual(redactValue(opener, { key: 'note' }), WITHHELD, 'the opener is harmless text');
  let worst = 0;
  for (const unit of UNITS) {
    for (const key of [null, 'note']) {
      const r = check(`redactValue of ${JSON.stringify(unit)} (${key === null ? 'no key' : 'under a key'})`, (n) => redactValue(`${opener}${textOf(unit, n - opener.length)}`, key === null ? {} : { key }), ABS_READ_MS);
      worst = Math.max(worst, r.t20);
    }
  }
  assert.ok(worst < ABS_READ_MS);
  console.log(`whole read: the slowest of ${UNITS.length * 2} texts takes ${worst.toFixed(2)} ms for 20000 characters`);
});

test('AC12 [r7] the reviewer\'s own probe: one entity with 200 attributes of a 19990-character near-miss text (a space, .local, @, then 0123. repeated) used to take 37941 ms; now it takes a few milliseconds and says what it did not read', () => {
  const text = (' .local @ x ' + '0123.'.repeat(4000)).slice(0, 19990);
  assert.equal(text.length, 19990);
  const attrs = {};
  for (let i = 0; i < 200; i += 1) attrs[`k${i}`] = text;
  let t0 = performance.now();
  const out = redactAttributes(attrs);
  const redactMs = performance.now() - t0;
  const shown = Object.values(out).filter((v) => v !== WITHHELD);
  assert.equal(shown.length, Math.floor(LIMITS.entityChars / 19990), 'the text is read as long as the budget pays for it, then withheld');
  assert.equal(Object.values(out).filter((v) => v === WITHHELD).length, 200 - shown.length);
  assert.ok(redactMs < 1500, `${redactMs.toFixed(0)} ms for redactAttributes (it was 37906 ms)`);
  const states = { 'sensor.ecco_intel_zz': { entity_id: 'sensor.ecco_intel_zz', state: '1', attributes: attrs, last_updated: new Date(NOW - 10000).toISOString(), last_changed: new Date(NOW - 10000).toISOString() } };
  const cat = validateCatalogue(miniCatalogue()).catalogue;
  t0 = performance.now();
  const snap = buildSnapshot(states, cat, NOW);
  const snapMs = performance.now() - t0;
  assert.ok(snapMs < 1500, `${snapMs.toFixed(0)} ms for buildSnapshot`);
  const row = snap.rows.find((r) => r.entity_id === 'sensor.ecco_intel_zz');
  assert.ok(row.withheld >= 195, `the row says how much it withheld (${row.withheld})`);
  assert.ok(row.attributes.some((a) => a.name.includes('values not read')), 'and the attribute list says that values were not read');
});

test('AC12 [r7] the whole entity, whatever its shape, is bounded: the reviewer\'s four hostile shapes each take well under a second (a text of every near-miss unit, a list of 200 near-miss items under one 20000-character key, 200 keys of 20000 characters, a dict of 5000 short near-miss strings)', () => {
  const bound = 1500;
  const timeOf = (label, attrs) => {
    const t0 = performance.now();
    const out = redactAttributes(attrs, { extraKeyPatterns: ['site_owner', 'zq_marker', 'a_b'] });
    const ms = performance.now() - t0;
    assert.ok(ms < bound, `${label}: ${ms.toFixed(0)} ms`);
    return { ms, out };
  };
  // (1) every unit as one attribute of 19990 characters
  const a = {};
  UNITS.slice(0, 200).forEach((u, i) => { a[`u${i}`] = textOf(u, 19990); });
  timeOf('one attribute per unit', a);
  // (2) a list of 200 near-miss items under ONE key of 20000 characters (the key was re-read for every item)
  const longKey = `${'k_'.repeat(9990)}ab`;
  assert.ok(longKey.length <= LIMITS.scanBound);
  timeOf('a list of 200 items under a key of 20000 characters', { [longKey]: Array.from({ length: 200 }, () => textOf('0123.', 4000)) });
  // (3) 200 keys, each of 20000 characters, each a near-miss text
  const keys = {};
  for (let i = 0; i < 200; i += 1) keys[`${'a.'.repeat(9990)}${String(i).padStart(4, 'x')}`] = 'v';
  timeOf('200 keys of 20000 characters', keys);
  // (4) a wide dict of short near-miss strings
  const wide = {};
  for (let i = 0; i < 5000; i += 1) wide[`w${i}`] = textOf(UNITS[i % UNITS.length], 120);
  timeOf('5000 short near-miss strings', wide);
  // (5) the same hostile entity through the export (each exported row has a budget of its own, and the export re-reads what the first read kept)
  const states = miniStates((s) => {
    for (let i = 0; i < 20; i += 1) s[`sensor.ecco_intel_hostile_${i}`] = mkState(`sensor.ecco_intel_hostile_${i}`, 'ok', { ...a, friendly_name: `Hostile ${i}` });
  });
  const t1 = performance.now();
  const snap = buildSnapshot(states, validateCatalogue(miniCatalogue()).catalogue, NOW);
  const snapMs = performance.now() - t1;
  assert.ok(snapMs < 4000, `${snapMs.toFixed(0)} ms for a snapshot with 20 hostile entities`);
  const t2 = performance.now();
  const json = exportRows(snap.rows, 'json', { nowMs: NOW });
  const csv = exportRows(snap.rows, 'csv', { nowMs: NOW });
  assert.ok(performance.now() - t2 < 4000, `${(performance.now() - t2).toFixed(0)} ms for both exports of 20 hostile entities`);
  assert.ok(json.length > 1000 && csv.length > 1000);
});

test('AC12 [r7] the cost per character of the worst shape, times the scan budget, is a small part of a second: this is why LIMITS.entityChars has the value it has', () => {
  assert.equal(LIMITS.entityChars, 100000);
  let worstPerChar = 0;
  let worstUnit = '';
  for (const unit of UNITS) {
    const text = `${' @ . : ; = / - ? # + pass= eyJ '}${textOf(unit, 19000)}`;
    const ms = leastMs(() => redactValue(text, { key: 'note' }), { trials: 2 });
    if (ms / text.length > worstPerChar) {
      worstPerChar = ms / text.length;
      worstUnit = unit;
    }
  }
  const worstEntityMs = worstPerChar * LIMITS.entityChars;
  console.log(`worst shape ${JSON.stringify(worstUnit)}: ${(worstPerChar * 1000).toFixed(3)} microseconds per character, so ${worstEntityMs.toFixed(1)} ms for a whole budget of ${LIMITS.entityChars} characters`);
  assert.ok(worstEntityMs < 500, `${worstEntityMs.toFixed(0)} ms to read a whole budget of the worst shape`);
});

test('AC12 [r7] the control: harmless text of the same lengths is read at a small fraction of those bounds, and every harmless text of up to the display cap is still shown whole (no budget effect on ordinary data)', () => {
  // review round 8: 400 entities of 4200 characters (1.7 million characters) are within the snapshot budget and are all read whole (2000 of them are not: the snapshot says which it did not read)
  const t0 = performance.now();
  const states = miniStates((s) => {
    for (let i = 0; i < 400; i += 1) s[`sensor.ecco_intel_long_${i}`] = mkState(`sensor.ecco_intel_long_${i}`, 'ok', { long_text: 'The planner checked the overnight window. '.repeat(100).slice(0, 4200) });
  });
  const snap = buildSnapshot(states, validateCatalogue(miniCatalogue()).catalogue, NOW);
  const ms = performance.now() - t0;
  assert.ok(ms < 4000, `${ms.toFixed(0)} ms for 400 entities`);
  assert.equal(snap.counts.unread, 0, 'ordinary data is not touched by the snapshot budget');
  const r = snap.rows.find((x) => x.entity_id === 'sensor.ecco_intel_long_7');
  assert.equal(r.redacted.long_text.startsWith('The planner checked'), true);
  assert.equal(r.attributes.some((a) => a.name.includes('values not read')), false);
});

// ===========================================================================================================================
// Review round 8 ([r8]): the SNAPSHOT budget. The entity budget bounds one entity; nothing bounded the total, so the FIRST render of a view with many entities of hostile text took 1 s for 50 of them, 4 s for 200 and
// 112 s for 5000 (reviewer probes perf8 and perf8n). A snapshot now reads at most LIMITS.snapshotChars across all its entities (budget.test.mjs tests what it does; this tests how long it takes).
// ===========================================================================================================================
const SNAPSHOT_FAMILIES = [
  ['eyJ-', 'a JWT start repeated'], [' .local @ x ', 'a host name suffix and an at sign'], ['0123.', 'a dotted run of digits'], ['0123.4567.8901.a', 'dotted addresses with a letter'], ['?token=', 'a token parameter'], ['?tokentoken', 'key words with no equals sign'],
  ['a.b@', 'an e-mail local part'], ['a@b.c1.', 'an e-mail domain'], ['host=host=', 'connection pairs with no semicolon'], ['a://u', 'a URL scheme'], ['-----BEGIN ', 'a key block start'], ['hooks.', 'a webhook host'],
  ['ab:cd:', 'colon groups'], ['pass=', 'a password pair'], ['a-b-', 'hyphen groups'], ['normal words here ', 'ordinary words'],
];
const hostileEntities = (n, text) => {
  const states = {};
  for (let i = 0; i < n; i += 1) {
    const id = `sensor.ecco_intel_s${i}`;
    const a = {};
    for (let k = 0; k < 5; k += 1) a[`a${k}`] = `${text}${i % 10}`;
    states[id] = { entity_id: id, state: '1', attributes: a, last_updated: new Date(NOW - 10000).toISOString(), last_changed: new Date(NOW - 10000).toISOString() };
  }
  return states;
};
const discoverOnly = () => validateCatalogue({ ...miniCatalogue(), sources: [], alerts: [], exceptions: [] }).catalogue;

test('AC12 [r8] THE FIRST SNAPSHOT of 50, 200 and 5000 entities of near-miss text (JWT starts, at signs, host suffixes, dotted digits, token parameters and eleven more families, five attributes of 19999 characters each) stays under a second, and the time does not grow with the number of entities (reviewer probes perf8 and perf8n)', () => {
  const bound = 1000;
  let worst = { ms: 0, label: '' };
  const per = {};
  for (const [unit, what] of SNAPSHOT_FAMILIES) {
    const text = textOf(unit, 19999);
    const t = {};
    for (const n of [50, 200, 5000]) {
      const states = hostileEntities(n, text);
      const cat = discoverOnly();
      let ms = Infinity;
      let snapshot = null;
      for (let trial = 0; trial < 2; trial += 1) {
        const states2 = trial === 0 ? states : hostileEntities(n, text);
        const t0 = performance.now();
        snapshot = buildSnapshot(states2, trial === 0 ? cat : discoverOnly(), NOW);
        ms = Math.min(ms, performance.now() - t0);
      }
      assert.equal(snapshot.rows.length, n, `${what}: a row for every entity`);
      const read = snapshot.rows.filter((r) => !r.unread).length;
      assert.ok(read <= 20, `${what} x ${n}: ${read} entities read (each costs the whole entity budget)`);
      assert.equal(snapshot.counts.unread, n - read);
      assert.ok(ms < bound, `${what} x ${n}: ${ms.toFixed(0)} ms for the first snapshot (it was ${n === 50 ? 982 : n === 200 ? 3912 : 112856} ms before the snapshot budget)`);
      t[n] = ms;
      if (ms > worst.ms) worst = { ms, label: `${what} x ${n}` };
    }
    per[unit] = t;
    // not more than linear in the number of entities: 25 times the entities (200 -> 5000) must not cost more than 25 times the time, and in fact costs about the same, because the budget is fixed
    assert.ok(t[5000] / Math.max(t[200], 5) <= 25, `${what}: ${t[200].toFixed(0)} ms for 200 entities and ${t[5000].toFixed(0)} ms for 5000 (the snapshot budget makes the time independent of the number of entities)`);
    assert.ok(t[200] / Math.max(t[50], 5) <= 8, `${what}: ${t[50].toFixed(0)} ms for 50 entities and ${t[200].toFixed(0)} ms for 200`);
  }
  console.log(`first snapshot, hostile text: the slowest of ${SNAPSHOT_FAMILIES.length * 3} runs is ${worst.label} at ${worst.ms.toFixed(0)} ms (bound ${bound} ms)`);
});

test('AC12 [r8] the snapshot budget bounds the work whatever the SHAPE: 5000 entities that each carry twenty thousand small values, 5000 entities with 255-character near-miss ids, and 5000 small ordinary entities (all read) each take well under a second', () => {
  const cat = () => discoverOnly();
  // (1) values: 200 keys of lists of 100 numbers, 5000 entities (no characters to speak of; the values are what costs)
  const heavy = {};
  for (let k = 0; k < 200; k += 1) heavy[`k${k}`] = Array.from({ length: 100 }, (_, i) => i);
  const manyValues = {};
  for (let i = 0; i < 5000; i += 1) manyValues[`sensor.ecco_intel_v${i}`] = { entity_id: `sensor.ecco_intel_v${i}`, state: '1', attributes: { ...heavy, n: i }, last_updated: new Date(NOW - 10000).toISOString() };
  let t0 = performance.now();
  const a = buildSnapshot(manyValues, cat(), NOW);
  const msA = performance.now() - t0;
  assert.ok(msA < 1000, `${msA.toFixed(0)} ms for 5000 entities of twenty thousand values`);
  assert.ok(a.rows.filter((r) => !r.unread).length < 200, 'a value costs the snapshot something: far fewer than 5000 entities are read');
  assert.equal(a.rows.length, 5000);
  // (2) ids: 5000 entities whose ids are 255 characters of near-miss text (the id of an entity is read whether or not the entity is)
  const ids = {};
  for (let i = 0; i < 5000; i += 1) {
    const id = `sensor.ecco_intel_${textOf('a.b@c1.', 230 - String(i).length)}${i}`;
    ids[id] = { entity_id: id, state: '1', attributes: {}, last_updated: new Date(NOW - 10000).toISOString() };
  }
  t0 = performance.now();
  const b = buildSnapshot(ids, cat(), NOW);
  const msB = performance.now() - t0;
  assert.ok(msB < 1000, `${msB.toFixed(0)} ms for 5000 ids of 255 characters`);
  assert.equal(b.rows.length, 5000);
  // (3) ordinary small entities: all read, in a fraction of a second (5000 of them cost the snapshot about 250 characters each: 1.25 million of the 2 million)
  const small = {};
  for (let i = 0; i < 5000; i += 1) small[`sensor.ecco_intel_o${i}`] = { entity_id: `sensor.ecco_intel_o${i}`, state: String(i), attributes: { friendly_name: `Sensor ${i}`, unit_of_measurement: 'kW', a: 1, b: 'two', c: true }, last_updated: new Date(NOW - 10000).toISOString() };
  t0 = performance.now();
  const c = buildSnapshot(small, cat(), NOW);
  const msC = performance.now() - t0;
  assert.ok(msC < 1000, `${msC.toFixed(0)} ms for 5000 small entities`);
  assert.equal(c.counts.unread, 0, 'ordinary entities are all read: 5000 of them fit in the snapshot budget');
  assert.equal(c.rows.length, 5000);
  console.log(`first snapshot: 5000 entities of many values ${msA.toFixed(0)} ms, of long ids ${msB.toFixed(0)} ms, small and ordinary ${msC.toFixed(0)} ms`);
});

test('AC12 [r8] the cost per unit of the worst shape, times the snapshot budget, is a small part of a second: this is why LIMITS.snapshotChars has the value it has', () => {
  assert.equal(LIMITS.snapshotChars, 2000000);
  let worstPerUnit = 0;
  let worstUnit = '';
  for (const [unit] of SNAPSHOT_FAMILIES) {
    const states = hostileEntities(20, textOf(unit, 19999));
    const cat = discoverOnly();
    let ms = Infinity;
    let spent = 0;
    for (let trial = 0; trial < 3; trial += 1) {
      const t0 = performance.now();
      const snapshot = buildSnapshot(trial === 0 ? states : hostileEntities(20, textOf(unit, 19999)), trial === 0 ? cat : discoverOnly(), NOW);
      ms = Math.min(ms, performance.now() - t0);
      spent = snapshot.rows.reduce((n, r) => n + r.spent, 0);
    }
    assert.ok(spent > 0);
    if (ms / spent > worstPerUnit) {
      worstPerUnit = ms / spent;
      worstUnit = unit;
    }
  }
  const worstSnapshotMs = worstPerUnit * LIMITS.snapshotChars;
  console.log(`worst shape ${JSON.stringify(worstUnit)}: ${(worstPerUnit * 1e6).toFixed(0)} nanoseconds per unit, so ${worstSnapshotMs.toFixed(0)} ms for a whole snapshot budget of ${LIMITS.snapshotChars}`);
  assert.ok(worstSnapshotMs < 400, `${worstSnapshotMs.toFixed(0)} ms to read a whole snapshot budget of the worst shape`);
});
