// Review round 7 ([r7]): the redactor's scan, after the performance class was closed (perf.test.mjs). Four classes, each closed as a class and not as the reviewer's instance:
//  (1) the rules were rewritten so that none is more than linear; they must still withhold everything the round-6 rules withheld (a differential test against the round-6 patterns, kept below as
//      REFERENCE), and nothing a bound cut may make a secret appear;
//  (2) the per-entity SCAN BUDGET (LIMITS.entityChars): what it counts, what it withholds, and that it is per entity;
//  (3) the CHUNK class: a reader that scans overlapping chunks of a string passed every round-6 sweep kind because none was longer than its overlap (reviewer mutants N31, N32, N33); the LONG kinds
//      are secrets that only one rule recognises, and only whole, and are longer than any overlap;
//  (4) the KEY-FOLD class: a catalogue key fragment is matched on the FOLDED key (reviewer mutant N13), and on the key's words (the NIT: site-owner, "site owner", siteOwner).
import test from 'node:test';
import assert from 'node:assert/strict';
import { loadCard, miniCatalogue, miniStates, mkState, NOW } from './helpers.mjs';
import { SECRET_VALUES, SECRET_VALUES_R3, SECRET_VALUES_R4, filler, LONG_KINDS, LONG_CARRIERS, LONG_PASSWORD_LENGTHS, longCases, longStarts, longStride, longPassword, carrier } from './secrets.mjs';

const core = await loadCard('scan7');
const { WITHHELD, LIMITS, SCAN_RULES, redactValue, redactAttributes, buildSnapshot, validateCatalogue, searchRows, exportRows, countWithheld } = core;

const snap = (mutate = null, catalogue = miniCatalogue()) => buildSnapshot(miniStates(mutate), validateCatalogue(catalogue).catalogue, NOW);
const byEntity = (s, eid) => s.rows.find((r) => r.entity_id === eid);
const DIAG = 'sensor.ecco_intel_new_diagnostic';
const rule = (reason) => SCAN_RULES.find((r) => r.reason === reason).pattern;
// every secret-shaped text is assembled from fragments, so that no file of the folder holds one (the folder scan of static.test.mjs)
const j = (...p) => p.join('');

// ===========================================================================================================================
// (1) the rewritten rules still withhold everything the round-6 rules withheld
// ===========================================================================================================================
// REFERENCE: the eleven patterns exactly as round 6 had them (the three read-ahead ones with their pre-tests, as the card ran them). They are slow on long texts, so they are used on short ones only.
const R6 = {
  'jwt': /\beyJ[\w-]{4,}\.[\w-]{4,}\.[\w-]*/,
  'key block': /-----BEGIN [A-Z0-9 ]+-----/,
  'url credentials': /\b[a-z][a-z0-9+.-]*:\/\/[^\s/?#@]*@/i,
  'url token': /[?&#;][\w.%-]*(?:token|secret|passw|pwd|apikey|api[_-]?key|auth|sig|signature|credential|session|bearer|jwt|key)[\w.%-]*=[^&\s]{3,}/i,
  'connection pairs': /\b(?:server|data source|host|hostname|uid|user ?id|userid|pwd|password|database|initial catalog)\s*=\s*[^;\s]+\s*;/i,
  'pass pair': /["']\s*(?:[a-z0-9_-]*[_-])?(?:pass|pw)\s*["']\s*:\s*["']?[^\s,;"']{3,}|(?<![a-z0-9])(?:[a-z0-9]+[_-])*(?:pass|pw)=["']?[^\s,;&"']{3,}/i,
  'email address': /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b/,
  'MAC address (dotted)': /\b(?=[0-9a-f.]*[a-f])[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}\b/i,
  'webhook path': /\/api\/webhook\/[A-Za-z0-9_-]{8,}|hooks\.[a-z0-9.-]+\/services\/[A-Za-z0-9/_-]{12,}/i,
  'internal host name': /\b[a-z][a-z0-9+.-]*:\/\/[a-z0-9-]+(?::\d{1,5})?(?=[/?#\s"']|$)/i,
  'private host name': /\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:local|lan|internal|home\.arpa|localdomain)\b/i,
};
// what the new rule is allowed to do differently, said as a test of the text (none for the exact ones)
// review round 8: the dotted MAC rule is exact again too (round 7 narrowed it: a letter after the address, as in 2026.1114.0900.beef, was no longer read; the round-8 rule is the round-6 verdict, in two alternatives that are each read once)
const EXACT = ['jwt', 'key block', 'url token', 'connection pairs', 'pass pair', 'webhook path', 'MAC address (dotted)'];
const SUPERSET = ['url credentials', 'internal host name', 'email address', 'private host name'];

// pieces from which short texts are built: the rule's own words, separators and near misses
const PIECES = {
  'jwt': ['eyJ', 'eyJhbGci', 'abcd', 'ab', '.', '-', '_', ' ', 'Zy9', '..', 'x', 'eyJabcd.', 'abcd.abcd.', 'eyJabcd.abcd.', 'eyJ-'],
  'key block': ['-----BEGIN ', '-----', 'RSA ', 'PRIVATE KEY', 'A', ' ', '-', 'x', 'BEGIN '],
  'url credentials': ['://', 'https', 'a', 'ws', '1', '_', '.', '-', '+', 'u', ':', 'p', '@', 'host', '/', '?', '#', ' ', 'A', 'https://', 'u:p@', 'user:pw@h', 'mqtt://'],
  'url token': ['?', '&', '#', ';', 'token', 'key', 'api_key', 'apikey', 'auth', 'sig', 'x', '_', '.', '-', '%', '=', 'abc', 'abcdef', ' ', 'Secret'],
  'connection pairs': ['Server', 'host', 'Host', 'uid', 'Pwd', 'user id', 'database', '=', ' ', ';', 'a', 'db1', '-', '(', '"', ',', 'initial catalog', 'data source', 'Server=db1;', 'uid=sa;', 'host=a', '; Pwd=x;'],
  'pass pair': ['pass', 'pw', 'PW', '"', "'", ':', '=', ' ', '_', '-', 'wifi', 'a', 'abc', 'hunter22', ',', ';', '&', 'x1', 'compass'],
  'email address': ['a', 'b', '@', '.', 'com', 'org', 'x', '-', '_', '+', '%', '1', ' ', 'co', 'ab.cd', '!', ','],
  'MAC address (dotted)': ['aabb', '1234', 'ccdd', 'eeff', '5678', '0900', '.', 'ab', 'a', '9', '.beef', ' ', 'AABB', '2026', 'aabb.ccdd.eeff', '1234.5678.9abc', 'a1b2.c3d4.', '2026.1114.0900'],
  'webhook path': ['/api/webhook/', 'abcdefgh', 'abc', 'hooks.', 'example', '.com', '/services/', 'T01/B02/abcdefghijkl', '.', '-', 'a', '/', ' ', 'x'],
  'internal host name': ['://', 'ws', 'http', 'a', 'host', ':', '8123', '123456', '/', '?', '#', ' ', '"', "'", '.', '-', '1', '_', 'nas'],
  'private host name': ['nas', 'a', '.', 'local', 'lan', 'internal', 'home.arpa', 'localdomain', '-', '_', '1', ' ', 'x', 'localhost', 'landing', 'B'],
};

function lcg(seed) {
  let s = seed >>> 0;
  return () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 4294967296;
  };
}

function corpusFor(reason, n = 8000) {
  const rnd = lcg(0xc0ffee + reason.length * 7919);
  const pieces = PIECES[reason];
  const out = new Set();
  // the fixed ones: every hostile fixture and every near miss the older suites use
  for (const s of [...SECRET_VALUES, ...SECRET_VALUES_R3, ...SECRET_VALUES_R4]) out.add(s.value);
  for (const s of ['nas.localhost', 'a.landing', 'x.internalsystem', 'x.home.arpas', 'version 2026.1114.0900', 'abc.abc.abc', 'compass=north', 'bypass: true', 'the pass was easy', 'pw is short', 'a.b.c.d.e', 'me@x', 'a@b.c',
    'https://example.org/path', 'user@host', '1.2.3', '2026.1114.0900.beef']) out.add(s);
  while (out.size < n) {
    const len = 1 + Math.floor(rnd() * 12);
    let t = '';
    for (let i = 0; i < len; i += 1) t += pieces[Math.floor(rnd() * pieces.length)];
    out.add(t);
  }
  return [...out];
}

test('AC10 [r7] DIFFERENTIAL: every rewritten rule still matches EVERYTHING the round-6 pattern matched, on thousands of short texts built from the rule\'s own words and near misses (no secret is lost to a bound)', () => {
  const total = {};
  for (const reason of Object.keys(R6)) {
    const now = rule(reason);
    const old = R6[reason];
    const corpus = corpusFor(reason);
    let oldHits = 0;
    const lost = [];
    const gained = [];
    for (const t of corpus) {
      const o = old.test(t);
      const n = now.test(t);
      if (o) oldHits += 1;
      if (o && !n) lost.push(t);
      if (!o && n) gained.push(t);
    }
    total[reason] = { texts: corpus.length, oldHits, lost: lost.length, gained: gained.length };
    assert.ok(oldHits >= 100, `${reason}: the corpus has ${oldHits} texts the round-6 rule matches (it must exercise the rule)`);
    // review round 8: the one narrowing of round 7 (the dotted MAC, where 2026.1114.0900.beef was no longer an address) is withdrawn: that rule is exact like the others
    assert.deepEqual(lost.slice(0, 5), [], `${reason}: ${lost.length} texts the round-6 rule matched are no longer matched`);
    if (EXACT.includes(reason)) assert.deepEqual(gained.slice(0, 5), [], `${reason}: ${gained.length} texts are matched that were not (an exact rewrite must not widen)`);
    else assert.ok(SUPERSET.includes(reason));
  }
  console.log(`differential: ${JSON.stringify(total)}`);
});

test('AC10 [r7] the widened rules widen in the safe direction only, and only in the shapes the design says: a scheme-less start of ://, an address with no word character before the at sign, a host name after an underscore', () => {
  const widened = [
    ['url credentials', j('1', ':', '//', 'user', ':', 'pw', '@', 'host'), true], ['url credentials', j('_a', ':', '//', 'user', ':', 'pw', '@', 'host'), true], ['url credentials', j('https', ':', '//', 'user', ':', 'pw', '@', 'host'), true], ['url credentials', 'a b://c', false], ['internal host name', 'a b://c', true], ['url credentials', 'https://host/path', false],
    ['internal host name', '1://nas', true], ['internal host name', 'ws://homeassistant:8123/x', true], ['internal host name', 'https://example.org/x', false], ['internal host name', 'ws:/nas', false],
    ['email address', j('a.b', '@', 'example.org'), true], ['email address', j('.', '@', 'example.org'), true], ['email address', j('x ', '@', 'example.org'), false], ['email address', 'me@x', false], ['email address', 'a@b.c', false],
    ['private host name', 'nas.local', true], ['private host name', 'my_nas.local', true], ['private host name', 'nas.localhost', false], ['private host name', ' .local', false], ['private host name', 'a.landing', false],
  ];
  for (const [reason, text, want] of widened) assert.equal(rule(reason).test(text), want, `${reason} on ${JSON.stringify(text)}`);
  // every text of the hostile fixtures that the round-6 rules withheld is still withheld by the whole read, with or without a key
  for (const s of [...SECRET_VALUES, ...SECRET_VALUES_R3, ...SECRET_VALUES_R4]) {
    assert.equal(redactValue(s.value), WITHHELD, s.label);
    assert.equal(redactValue(s.value, { key: 'note' }), WITHHELD, s.label);
  }
});

test('AC10 [r8] the bounds of round 7 are GONE (review round 8: each of these was pinned there as a limit, a text the rule did not match; each is now matched by the rule itself, whatever the length of the component, so no secret is shown because a part of it is long)', () => {
  // jwt: a first segment of any length and a second of any length
  const seg = (n) => 'eyJ' + 'aB3'.repeat(Math.ceil(n / 3)).slice(0, n - 3);
  assert.ok(rule('jwt').test(`${seg(512 + 3)}.${'x'.repeat(4096)}.sig`), 'a first segment of 512 characters after eyJ and a second of 4096 are matched');
  assert.equal(rule('jwt').test(`${seg(600)}.${'x'.repeat(100)}.sig`), true, 'a first segment longer than the old bound is matched by the rule itself (round 7 pinned this as false)');
  assert.equal(rule('jwt').test(`${seg(5000)}.${'x'.repeat(5000)}.sig`), true, 'and so are a first and a second segment of 5000 characters');
  assert.equal(redactValue(`${seg(600)}.${'x'.repeat(100)}.sig`), WITHHELD);
  const plain = (n) => 'eyJ' + 'abcdefgh-'.repeat(Math.ceil(n / 9)).slice(0, n);
  assert.equal(rule('jwt').test(`${plain(600)}.${'abcdefgh-'.repeat(5)}.sig`), true, 'a segment with no digit (no encoded-value rule can read it)');
  assert.equal(redactValue(`${plain(600)}.${'abcdefgh-'.repeat(5)}.sig`), WITHHELD);
  // webhook: a host name of any length
  assert.ok(rule('webhook path').test(j('hooks.', 'a'.repeat(253), '/services/', 'abcdefghijkl')));
  assert.ok(rule('webhook path').test(j('hooks.', 'a'.repeat(260), '/services/', 'abcdefghijkl')), 'a host of 260 characters (the DNS limit is 253)');
  // connection pairs: any length after any boundary
  const pair = (n) => j('Server', '=', 'x'.repeat(n), ';');
  assert.ok(rule('connection pairs').test(`(${pair(256)}`), '256 characters after a bracket');
  assert.equal(rule('connection pairs').test(`(${pair(257)}`), true, '257 characters after a bracket (round 7 pinned this as false)');
  assert.equal(rule('connection pairs').test(`(${pair(5000)}`), true, '5000 characters after a bracket');
  assert.equal(rule('connection pairs').test(j('x,host=', 'srv'.repeat(100), ';')), true, 'after a comma, with a value of 300 characters');
  assert.ok(rule('connection pairs').test(pair(20000 - 9)), 'any length at the start of the text');
  assert.ok(rule('connection pairs').test(`a ${pair(5000)}`) && rule('connection pairs').test(`a;${pair(5000)}`), 'and after a space or a semicolon');
  // url token: a parameter name of any length around the key word
  assert.ok(rule('url token').test(j('?', 'a'.repeat(64), 'token', 'b'.repeat(64), '=abc')));
  assert.equal(rule('url token').test(j('?', 'a'.repeat(65), 'token=abc')), true, 'a name of 65 characters before the key word (round 7 pinned this as false; a real value was shown)');
  assert.equal(rule('url token').test(j('?token', 'a'.repeat(65), '=abc')), true, 'and after it');
  assert.equal(rule('url token').test(j('?', 'a'.repeat(3000), 'token', 'b'.repeat(3000), '=abc')), true, 'and 3000 on both sides');
  // key block: a label of any length
  assert.ok(rule('key block').test(j('-----BEGIN ', 'A'.repeat(64), '-----')));
  assert.equal(rule('key block').test(j('-----BEGIN ', 'A'.repeat(65), '-----')), true, 'a label of 65 characters (round 7 pinned this as false)');
  assert.equal(rule('key block').test(j('-----BEGIN ', 'OPENSSH PRIVATE KEY '.repeat(4), '-----')), true, 'and of 80');
  // the dotted MAC: a letter after the address, anywhere in the same run
  assert.equal(rule('MAC address (dotted)').test('2026.1114.0900.beef'), true, 'a letter after the address (round 7 let this one through)');
  assert.equal(rule('MAC address (dotted)').test(j('0123.4567.8901.', '0'.repeat(3000), 'a')), true, 'a letter 3000 characters after the address');
  assert.equal(rule('MAC address (dotted)').test('2026.1114.0900'), false, 'all digits and nothing after it is a version, not an address');
  assert.equal(rule('MAC address (dotted)').test('2026.1114.0900 beef'), false, 'a letter after a space is not in the same run');
});

// ===========================================================================================================================
// (2) the scan budget
// ===========================================================================================================================
test('AC12 [r7] the scan budget: LIMITS.entityChars is 100000, 25 times the largest real entity and five of the longest strings the card reads', () => {
  assert.equal(LIMITS.entityChars, 100000);
  assert.ok(LIMITS.entityChars >= 4 * LIMITS.scanBound, 'at least four whole strings of the longest length');
  assert.ok(LIMITS.entityChars <= 10 * LIMITS.scanBound, 'and a bound on the work of one entity, not a licence');
});

test('AC12 [r7] a budget pays for strings in order and withholds every string after the last it can pay for: harmless texts of 1000 characters, 100 of them, are read until the budget is gone, then withheld, and never again read', () => {
  const attrs = {};
  for (let i = 0; i < 150; i += 1) attrs[`t${String(i).padStart(3, '0')}`] = `${i} ${filler(997)}`;
  const out = redactAttributes(attrs);
  // a name that is not read is shown as a withheld key, so the entries are read in order
  const entries = Object.entries(out);
  assert.equal(entries.length, 150);
  const flags = entries.map(([, v]) => v === WITHHELD);
  const firstWithheld = flags.indexOf(true);
  assert.ok(firstWithheld >= 90 && firstWithheld <= 100, `the first withheld text is number ${firstWithheld}`);
  assert.ok(flags.slice(firstWithheld).every(Boolean), 'once one is withheld for want of budget, all that follow are');
  assert.ok(flags.slice(0, firstWithheld).every((f) => !f), 'every one before it was read and shown');
  assert.equal(out.t000, attrs.t000, 'a text within the budget is shown exactly as before');
  assert.ok(entries.slice(firstWithheld + 1).every(([k]) => k.startsWith('[withheld key')), 'and a name that the budget could not pay for is not shown either');
});

test('AC12 [r7] the budget is per ENTITY: two entities each read their whole budget; the state, the unit and the name draw on the same budget as the attributes; and an export row has a budget of its own', () => {
  const big = (marker) => ({ a: `${marker}A ${filler(19900)}`, b: `${marker}B ${filler(19900)}`, c: `${marker}C ${filler(19900)}`, d: `${marker}D ${filler(19900)}`, e: `${marker}E ${filler(19900)}`, f: `${marker}F ${filler(19900)}` });
  const s = snap((states) => {
    states['sensor.ecco_intel_budget_one'] = mkState('sensor.ecco_intel_budget_one', 'ok', big('one'));
    states['sensor.ecco_intel_budget_two'] = mkState('sensor.ecco_intel_budget_two', 'ok', big('two'));
  });
  for (const [eid, m] of [['sensor.ecco_intel_budget_one', 'one'], ['sensor.ecco_intel_budget_two', 'two']]) {
    const r = byEntity(s, eid);
    assert.ok(r.redacted.a.startsWith(`${m}A `), `${eid}: the first text is read and shown`);
    assert.equal(r.redacted.f, WITHHELD, `${eid}: the sixth text is past the budget and is withheld, unread`);
    assert.ok(r.withheld >= 1);
    const names = r.attributes.map((x) => x.name);
    assert.ok(names.some((n) => n.includes('values not read')), `${eid}: the attribute list says that values were not read`);
    assert.ok(!JSON.stringify(r.redacted).includes(`${m}F `), `${eid}: nothing of the unread text is in the raw attributes`);
    assert.equal(searchRows(s.rows, `${m}f `).filter((x) => x.entity_id === eid).length, 0, `${eid}: or in the search text`);
  }
  // the export: rows are separate entities (a row that has used its budget does not take another's)
  const rows = [byEntity(s, 'sensor.ecco_intel_budget_one'), byEntity(s, 'sensor.ecco_intel_budget_two'), byEntity(s, 'sensor.ecco_intel_budget_one')];
  const json = JSON.parse(exportRows(rows, 'json', { nowMs: NOW }));
  for (const item of json.rows) {
    assert.ok(typeof item.attributes.a === 'string' && item.attributes.a !== WITHHELD, 'every exported row still has its first text');
    assert.ok(typeof item.attributes.e === 'string' && item.attributes.e !== WITHHELD, 'and its fifth: the export reset the budget for each row');
  }
  // a state that is a long text draws on the same budget as the attributes. Review round 8: it is charged and read FIRST (round 7 read it last, so that the state of an entity whose attributes used the budget was withheld,
  // and the headline of the row was lost): now the state is read and shown, and it is the attributes past the budget that are withheld
  const t = snap((states) => { states['sensor.ecco_intel_budget_three'] = mkState('sensor.ecco_intel_budget_three', filler(200), { ...big('three'), a: filler(19900), b: filler(19900), c: filler(19900), d: filler(19900), e: filler(19900), f: filler(19900) }); });
  const three = byEntity(t, 'sensor.ecco_intel_budget_three');
  assert.equal(three.stateText, filler(200), 'the state of an entity whose attributes used the budget is read first, and shown');
  assert.equal(three.redacted.f, WITHHELD, 'and the attribute past the budget is withheld');
  // a state that LOOKS secret is withheld wherever it is read (the order changed what is charged first, not what is withheld)
  const u = snap((states) => { states['sensor.ecco_intel_budget_four'] = mkState('sensor.ecco_intel_budget_four', j('gh', 'p_', 'A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8'), { ...big('four') }); });
  assert.equal(byEntity(u, 'sensor.ecco_intel_budget_four').stateText, WITHHELD, 'a state that looks like a token is withheld although it is read first');
});

test('AC12 [r7] key names are read within the budget too: 600 keys of about 107 characters in nested dicts are read until the budget is gone, then every key is shown as withheld and its value is withheld', () => {
  const dicts = {};
  for (let d = 0; d < 4; d += 1) {
    const inner = {};
    for (let k = 0; k < 150; k += 1) inner[`${String(d).padStart(2, '0')}_${String(k).padStart(3, '0')}_${'k'.repeat(100)}`] = 'v';
    dicts[`group_${d}`] = inner;
  }
  const out = redactAttributes(dicts);
  let read = 0;
  let hiddenKeys = 0;
  let hiddenValues = 0;
  const edge = [];
  const walk = (o) => {
    for (const [k, v] of Object.entries(o)) {
      const isMarker = k.startsWith('[withheld key');
      if (isMarker) hiddenKeys += 1;
      else if (/^[0-9]{2}_[0-9]{3}_k+$/.test(k)) read += 1;
      if (v === WITHHELD) hiddenValues += 1;
      if (isMarker) assert.equal(v, WITHHELD, 'a key that was not read has a value that was not read');
      else if (/^[0-9]{2}_[0-9]{3}_k+$/.test(k) && v !== 'v') edge.push(k);
      if (v !== null && typeof v === 'object') walk(v);
    }
  };
  walk(out);
  // a key of 107 characters costs about 215 (it is read as a name and as a key), so a budget of 100000 pays for about 465 of the 600
  assert.ok(read >= 430 && read <= 500, `${read} keys read of 600`);
  assert.ok(hiddenKeys >= 100, `${hiddenKeys} keys withheld unread`);
  assert.ok(edge.length <= 1, 'at most the one key the budget ran out on is shown with its value withheld (its name was read, its value could not be paid for)');
  assert.equal(read + hiddenKeys, 600 + (4 - Object.keys(out).filter((k) => k.startsWith('group_')).length), 'every key is either read or withheld, none is lost (a group name past the budget is one more withheld key)');
  assert.equal(countWithheld(out), hiddenKeys + hiddenValues, 'the key and the value are each counted');
  assert.equal(Object.keys(out.group_0).filter((k) => k.startsWith('[withheld key')).length, 0, 'the first group is read whole');
});

test('AC12 [r7] a list of 200 items under ONE key is not read through that key 200 times: the key is looked at once (the reviewer\'s list-under-a-long-key shape)', () => {
  const longKey = `${'ab_'.repeat(6600)}x`;
  assert.ok(longKey.length < LIMITS.scanBound);
  const items = Array.from({ length: 200 }, (_, i) => `item ${i}`);
  const t0 = performance.now();
  const out = redactAttributes({ [longKey]: items });
  const ms = performance.now() - t0;
  const only = Object.values(out)[0];
  assert.equal(only.length, 200);
  assert.ok(only.every((v, i) => v === `item ${i}`), 'a harmless key keeps its harmless items');
  assert.ok(ms < 300, `${ms.toFixed(0)} ms`);
  // and with a catalogue fragment, where each read of the key is a search of 165 windows against 40 fragments
  const frags = Array.from({ length: 40 }, (_, i) => `zq_fragment_${i}`);
  const t1 = performance.now();
  redactAttributes({ [longKey]: items }, { extraKeyPatterns: frags });
  assert.ok(performance.now() - t1 < 300, `${(performance.now() - t1).toFixed(0)} ms with 40 fragments`);
});

test('AC12 [r7] ordinary data is not touched by the budget: every Intelligence fixture is read whole (no value withheld for want of budget, no note), and the unread-values note appears only past the budget', () => {
  const s = snap();
  for (const r of s.rows) assert.equal(r.attributes.some((a) => a.name.includes('values not read')), false, `${r.entity_id}`);
  const t = snap((states) => { states[DIAG].attributes.huge_a = filler(19990); states[DIAG].attributes.huge_b = filler(19990); });
  assert.equal(byEntity(t, DIAG).attributes.some((a) => a.name.includes('values not read')), false, 'two long texts are within the budget');
});

// ===========================================================================================================================
// (3) the chunk class: LONG kinds, recognised only whole
// ===========================================================================================================================
test('AC10 [r7] the long kinds are what they say: seven kinds, one rule each, recognised only whole (no head, no tail, no piece of any of them is withheld, apart from a head that already holds the whole user-info)', () => {
  assert.deepEqual([...LONG_PASSWORD_LENGTHS], [150, 300, 600, 1200, 3000]);
  assert.deepEqual([...LONG_CARRIERS], [4500, 12000, 20000]);
  assert.equal(LONG_KINDS.length, 7);
  for (const k of LONG_KINDS) {
    const rules = SCAN_RULES.filter((r) => r.pattern.test(k.value)).map((r) => r.reason);
    assert.deepEqual(rules, [k.rule], `${k.label}: exactly the rule it is about recognises it`);
    assert.equal(redactValue(k.value, { key: 'note' }), WITHHELD, k.label);
    assert.ok(k.value.includes(k.probe) && !filler(30000).includes(k.probe));
    const end = k.value.indexOf(k.rule === 'url credentials' ? '@' : ';') + 1;
    for (let c = 1; c < k.value.length; c += 13) {
      const head = k.value.slice(0, c);
      const tail = k.value.slice(c);
      if (c < end && c > 24) assert.notEqual(redactValue(head, { key: 'note' }), WITHHELD, `${k.label}: the head of ${c} characters stands alone`);
      if (c > 8 && c < end - 1) assert.notEqual(redactValue(tail, { key: 'note' }), WITHHELD, `${k.label}: the tail from ${c} stands alone`);
    }
  }
  assert.equal(longPassword(150).length, 150);
  assert.ok(longPassword(150).endsWith('!'));
  assert.ok(!/[A-Za-z0-9]{4}/.test(longPassword(3000)), 'no run of four letters or digits: no base64, hex or word rule can see a part');
  assert.equal(longStride(150), 12);
  assert.equal(longStride(3033), 252);
  for (const k of LONG_KINDS) for (const total of LONG_CARRIERS) {
    const starts = longStarts(k.value.length, total);
    assert.equal(starts[0], 0);
    assert.equal(starts[starts.length - 1], total - k.value.length, 'the last start puts the secret at the very end');
    assert.ok(starts.length > (total - k.value.length) / longStride(k.value.length) - 1);
    const text = carrier(k.value, starts[Math.floor(starts.length / 2)], total);
    assert.equal(text.length, total);
  }
});

test('AC10 [r7] LONG SWEEP: every long kind is withheld at every start of a stride below its length, in carriers of 4500, 12000 and 20000 characters (a chunked reader with an overlap shorter than the secret fails here: reviewer mutants N31, N32, N33)', () => {
  let n = 0;
  const failures = [];
  for (const c of longCases()) {
    n += 1;
    if (redactValue(c.text, { key: 'note' }) !== WITHHELD) failures.push(c.label);
  }
  assert.ok(n >= 5000, `${n} cases`);
  assert.deepEqual(failures.slice(0, 8), [], `${failures.length} of ${n} cases show the secret`);
});

test('AC10 [r7] LONG SWEEP, every door of the core: no key, a dict value, a list item, an attribute object, a revision key, with the catalogue fragments, at the boundary-near starts of every carrier', () => {
  const failures = [];
  let n = 0;
  const pick = (len, total) => [...new Set(longStarts(len, total).filter((_, i, a) => i % 7 === 0 || i === a.length - 1))];
  for (const c of longCases(LONG_CARRIERS, pick)) {
    n += 1;
    const doors = [redactValue(c.text), redactValue({ a: { b: [c.text] } }).a.b[0], redactValue({ [`k_${c.id}`]: c.text })[`k_${c.id}`], redactAttributes({ sweep_note: c.text }).sweep_note,
      redactValue([c.text, 'x'])[0], redactValue(c.text, { key: 'git_sha' }), redactValue(c.text, { key: 'note', extraKeyPatterns: ['site_owner'] })];
    if (doors.some((d) => d !== WITHHELD)) failures.push(c.label);
  }
  assert.ok(n >= 700, `${n} cases`);
  assert.deepEqual(failures.slice(0, 8), [], `${failures.length} cases show the secret`);
});

test('AC10 [r7] LONG SWEEP, the row paths: a long kind in an attribute and in a state is withheld in the row, the raw attributes, the search index and both exports; the control with filler is shown (cut at the cap)', () => {
  const pick = (len, total) => [...new Set([0, 1, 2999, 3000, 3001, 4000 - Math.ceil(len / 2), total - len - 1, total - len].filter((s) => s >= 0 && s + len <= total))];
  const cases = [...longCases([4500, 20000], pick)];
  assert.ok(cases.length >= 100, `${cases.length}`);
  // review round 8: a snapshot reads at most LIMITS.snapshotChars characters across all its entities, and these cases are several million characters, so they are read in snapshots of 30 cases (60 entities, under a
  // million characters each): the snapshot budget is not what is under test here, and every assertion is made on every batch, with every probe looked for in every batch
  const BATCH = 30;
  const probes = [...new Set(cases.map((c) => c.probe))];
  const failures = [];
  for (let from = 0; from < cases.length; from += BATCH) {
    const batch = cases.slice(from, from + BATCH);
    const s = snap((states) => {
      for (const c of batch) {
        states[`sensor.ecco_intel_lg_${c.id}`] = mkState(`sensor.ecco_intel_lg_${c.id}`, 'ok', { long_note: c.text, friendly_name: `Long ${c.id}` });
        states[`sensor.ecco_intel_lgstate_${c.id}`] = mkState(`sensor.ecco_intel_lgstate_${c.id}`, c.text, { friendly_name: `Long state ${c.id}` });
      }
    });
    assert.equal(s.counts.unread, 0, `batch ${from}: the snapshot budget is not used up`);
    const byId = new Map(s.rows.map((r) => [r.entity_id, r]));
    for (const c of batch) {
      if (byId.get(`sensor.ecco_intel_lg_${c.id}`).redacted.long_note !== WITHHELD) failures.push(`${c.label}: attribute`);
      if (byId.get(`sensor.ecco_intel_lgstate_${c.id}`).stateText !== WITHHELD) failures.push(`${c.label}: state`);
    }
    const everything = JSON.stringify(s.rows.map((r) => [r.stateText, r.attributes, r.redacted, r.searchText, r.title]));
    const exported = exportRows(s.rows, 'json', { nowMs: NOW }) + exportRows(s.rows, 'csv', { nowMs: NOW });
    for (const probe of probes) {
      assert.ok(!everything.includes(probe), 'a row carries a piece of a long secret');
      assert.ok(!exported.includes(probe), 'an export carries a piece of a long secret');
      assert.equal(searchRows(s.rows, probe.toLowerCase()).length, 0);
    }
    for (const k of LONG_KINDS) assert.ok(!everything.includes(k.value) && !exported.includes(k.value), `${k.label}: the whole secret is nowhere`);
  }
  assert.deepEqual(failures.slice(0, 8), []);
  // the control: the same carrier with filler where the secret was is shown whole, up to the display cap
  const clean = filler(4500);
  const s2 = snap((states) => { states['sensor.ecco_intel_lg_control'] = mkState('sensor.ecco_intel_lg_control', 'ok', { long_note: clean }); });
  assert.equal(byEntity(s2, 'sensor.ecco_intel_lg_control').redacted.long_note, `${clean.slice(0, 4000)}\u2026 [truncated 500 more characters]`);
});

// ===========================================================================================================================
// (4) the key-fold class
// ===========================================================================================================================
const FOLD_VARIANTS = [
  ['plain', 'site_owner'], ['upper case', 'SITE_OWNER'], ['mixed case', 'Site_Owner'],
  ['zero-width space', 'site_\u200bowner'], ['zero-width joiner', 'site\u200d_owner'], ['zero-width non-joiner', 'si\u200cte_owner'], ['word joiner', 'site_\u2060owner'], ['byte order mark', 'site_\ufeffowner'],
  ['soft hyphen', 'site_o\u00adwner'], ['right-to-left override', 'site_\u202eowner'], ['left-to-right isolate', '\u2066site_owner\u2069'], ['right-to-left mark', 'site\u200f_owner'],
  ['Cyrillic o', 'site_\u043ewner'], ['Cyrillic e', 'sit\u0435_owner'], ['Cyrillic s', '\u0455ite_owner'], ['Cyrillic i and t', 's\u0456te_owner'], ['Greek omicron', 'site_\u03bfwner'], ['Greek iota', 's\u03b9te_owner'], ['Greek capital omicron', 'site_\u039fwner'],
  ['fullwidth s', '\uff53ite_owner'], ['fullwidth word', '\uff53\uff49\uff54\uff45_\uff4f\uff57\uff4e\uff45\uff52'], ['fullwidth upper', '\uff33\uff29\uff34\uff25_\uff2f\uff37\uff2e\uff25\uff32'],
  ['hyphen', 'site-owner'], ['space', 'site owner'], ['camel case', 'siteOwner'], ['dot', 'site.owner'], ['hyphen and upper case', 'SITE-OWNER'], ['camel case with a zero-width space', 'site\u200bOwner'],
  ['Cyrillic and a hyphen', 'site-\u043ewner'], ['hyphen, bidi and Greek', '\u202esite-\u03bfwner'], ['wrapped in other words', 'my_site_owner_name'], ['wrapped camel case', 'mySiteOwnerName'],
];

test('AC10 [r7] KEY FOLD (reviewer mutant N13): the catalogue fragment site_owner withholds the value under EVERY form of the key: upper case, zero-width and bidi characters, Cyrillic and Greek look-alikes, fullwidth letters, a hyphen, a space, a dot, camel case, wrapped in other words; in the raw attributes, a row, the search, and both exports', () => {
  assert.ok(FOLD_VARIANTS.length >= 30);
  const marker = (i) => `zq7foldmarker${String(i).padStart(2, '0')}`;
  const attrs = {};
  FOLD_VARIANTS.forEach(([, key], i) => { attrs[key] = marker(i); });
  assert.equal(new Set(Object.keys(attrs)).size, FOLD_VARIANTS.length, 'every variant is a different key');
  const raw = redactAttributes(attrs, { extraKeyPatterns: ['site_owner'] });
  FOLD_VARIANTS.forEach(([label], i) => {
    const kept = Object.values(raw).filter((v) => v === marker(i)).length;
    assert.equal(kept, 0, `${label}: the value is withheld in the raw attributes`);
  });
  assert.equal(Object.values(raw).filter((v) => v === WITHHELD).length, FOLD_VARIANTS.length);
  // control: the same keys without the fragment (no catalogue pattern) show every value, so it is the fragment that withholds
  const control = redactAttributes(attrs);
  FOLD_VARIANTS.forEach(([label], i) => assert.equal(Object.values(control).filter((v) => v === marker(i)).length, 1, `${label}: shown without the fragment`));
  // the same through a snapshot and everything made from it
  const s = snap((states) => { Object.assign(states[DIAG].attributes, attrs); });
  const r = byEntity(s, DIAG);
  const everything = JSON.stringify([r.attributes, r.redacted, r.searchText, r.stateText]) + exportRows([r], 'json', { nowMs: NOW }) + exportRows([r], 'csv', { nowMs: NOW });
  FOLD_VARIANTS.forEach(([label], i) => {
    assert.ok(!everything.includes(marker(i)), `${label}: the value reaches the row, the raw view, the search text or an export`);
    assert.equal(searchRows(s.rows, marker(i)).length, 0, `${label}: a search finds it`);
  });
  assert.ok(r.withheld >= FOLD_VARIANTS.length);
});

test('AC10 [r7] KEY FOLD: a fragment that no word join can find is matched on the folded key as written (fragment siteo across a camel-case boundary and a zero-width space; x__y against a Cyrillic y), so the fold itself is what is tested (reviewer mutant N13)', () => {
  const cases = [['siteo', 'site\u200bOwner'], ['siteo', 'site\u200bowner'], ['x__y', 'x__\u0443'], ['x__y', 'x__y'], ['ite_ow', 'S\uff49te_\u043ewner'], ['owner', 'my\u200bOwner'], ['1_a', '1_\u0430']];
  for (const [fragment, key] of cases) {
    const out = redactAttributes({ [key]: 'zq7value' }, { extraKeyPatterns: [fragment] });
    assert.deepEqual(Object.values(out), [WITHHELD], `fragment ${fragment} against ${JSON.stringify(key)}`);
  }
  // and the fold is never an over-match: a key that does not hold the fragment, in any form, is shown
  for (const [fragment, key] of [['site_owner', 'site_own'], ['site_owner', 'sit_owner'], ['siteo', 'sit\u200be'], ['x__y', 'x_y'], ['owner', 'own er']]) {
    const out = redactAttributes({ [key]: 'zq7value' }, { extraKeyPatterns: [fragment] });
    assert.deepEqual(Object.values(out), ['zq7value'], `fragment ${fragment} against ${JSON.stringify(key)} is not a match`);
  }
});

test('AC10 [r7] KEY FOLD (the NIT): site-owner, "site owner", siteOwner, site.owner and SITE_OWNER are withheld by the fragment site_owner, as site_owner is; the words are matched with an underscore between them', () => {
  for (const key of ['site-owner', 'site owner', 'siteOwner', 'site.owner', 'SITE_OWNER', 'Site-Owner', 'site__owner', 'site_-_owner', '  site owner  ', 'ownerSite_owner']) {
    assert.deepEqual(Object.values(redactAttributes({ [key]: 'zq7value' }, { extraKeyPatterns: ['site_owner'] })), [WITHHELD], key);
  }
  // not a loosening of anything else: a fragment with a digit or a longer word still means what it said
  assert.deepEqual(Object.values(redactAttributes({ 'site-owners': 'zq7value' }, { extraKeyPatterns: ['site_owner'] })), [WITHHELD], 'a fragment is a part of a key (site_owner is a part of site-owners)');
  assert.deepEqual(Object.values(redactAttributes({ siteowner: 'zq7value' }, { extraKeyPatterns: ['site_owner'] })), ['zq7value'], 'one word is not two (siteowner has no underscore to find)');
  assert.deepEqual(Object.values(redactAttributes({ 'site-owner': 'zq7value' })), ['zq7value'], 'with no fragment nothing is withheld by this rule');
});
