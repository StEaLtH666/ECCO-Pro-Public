// Review round 8 ([r8]): THE DIFFERENTIAL GATE of the redactor's value rules.
//
// The class. Round 7 made every value rule linear by bounding some quantifiers ({0,64}, {1,256}, {4,512}, {4,4096}, {1,64}, {1,253}, {0,13}). A bounded rule stops matching a secret whose COMPONENT is longer than
// the bound, and the secret is then SHOWN: the reviewer of round 8 found a URL token parameter name of 65 characters (a real secret value shown), a connection pair after a bracket with a 300-character
// value, a JWT whose first segment is over 512 characters and a key block label of 80 characters, all withheld in round 6 and shown in round 7. A performance fix must never be a privacy regression.
//
// The gate. reference-r6.mjs is the round-6 rule set, frozen (commit f4e52be, unbounded). differential.mjs generates, for every kind of secret, the secret with ONE component at every length from 1 to
// 300 and then 400, 600 and 1000 (and at both sides of every bound a rule has had, in carriers of 4000 characters), at the start, in the middle and at the end of prose and with no prose. The assertion
// is one direction only: WHATEVER THE REFERENCE WITHHOLDS THE CARD STILL WITHHOLDS (the card may withhold more, never less). It is asserted twice: for the whole read (redactValue, the path every value
// takes) and rule by rule (so a rule that lost a match is named even if another rule would have withheld the text).
//
// The gate must be able to see the class: the round-7 bounded forms of the six rules are kept below (R7) and are shown to LOSE cases on this corpus (negative controls).
//
// This file is heavy (a few seconds), so the mutation runner gives it only to the mutants that are about the rules (`diff: true`) and to the baseline.
import test from 'node:test';
import assert from 'node:assert/strict';
import { loadCard } from './helpers.mjs';
import { REF_RULES, refReason, refRuleHits } from './reference-r6.mjs';
import { FAMILIES, DENSE, SPARSE, W, cases } from './differential.mjs';

const core = await loadCard('diff8');
const { WITHHELD, SCAN_RULES, redactValue } = core;

const cardRule = (reason) => SCAN_RULES.find((r) => r.reason === reason);
const refRule = (reason) => REF_RULES.find((r) => r.reason === reason);
/** What the card's rule (its gate, its pre-test and its pattern, as valueReason runs them) says about an ASCII text. */
const cardRuleHits = (rule, text) => {
  if (rule.gate !== null && !text.includes(rule.gate)) return false;
  if (rule.pretest !== null && !rule.pretest.test(text)) return false;
  return rule.pattern.test(text);
};
const label = (c) => `${c.family} n=${c.n} ${c.place}`;
const ASCII = /^[\x20-\x7e]*$/;

// the round-7 forms of the six rules that lost matches (kept as they were, as negative controls)
const KEYS = 'server|data source|host|hostname|uid|user ?id|userid|pwd|password|database|initial catalog';
const R7 = {
  'jwt': /\beyJ[\w-]{4,512}\.[\w-]{4,4096}\.[\w-]*/,
  'key block': /-----BEGIN [A-Z0-9 ]{1,64}-----/,
  'url token': /[?&#;][\w.%-]{0,64}(?:token|secret|passw|pwd|apikey|api[_-]?key|auth|sig|signature|credential|session|bearer|jwt|key)[\w.%-]{0,64}=[^&\s]{3,}/i,
  'connection pairs': new RegExp(`\\b(?:${KEYS})\\s*=\\s*[^;\\s]{1,256}\\s*;|(?:^|[;\\s])(?:${KEYS})\\s*=\\s*[^;\\s]+\\s*;`, 'i'),
  'webhook path': /\/api\/webhook\/[A-Za-z0-9_-]{8,}|hooks\.[a-z0-9.-]{1,253}\/services\/[A-Za-z0-9/_-]{12,}/i,
  'MAC address (dotted)': /\b(?=[0-9a-f.]{0,13}[a-f])[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}\b/i,
};

test('AC10 [r8] the corpus is what it says: families of secrets, one component swept from 1 to 1000 characters, in prose and bare; the filler is inert and every family is read by the reference', () => {
  assert.ok(FAMILIES.length >= 40, `${FAMILIES.length} families`);
  assert.equal(DENSE.length, 303);
  assert.deepEqual([...DENSE.slice(0, 3), ...DENSE.slice(-4)], [1, 2, 3, 300, 400, 600, 1000]);
  for (const need of [63, 64, 65, 253, 254, 255, 256, 257, 511, 512, 513, 4095, 4096, 4097]) assert.ok(SPARSE.includes(need), `the sparse sweep has ${need}`);
  // no rule reads the filler as a secret, so it cannot hide a regression
  for (const n of [1, 6, 40, 300, 1000, 5000]) assert.equal(refReason(W(n)), null, `W(${n}) is inert`);
  assert.equal(refReason(W(5000)), null);
  // every family is detected by the reference (somewhere on the sweep), and each rule of the reference is the target of at least one family or is a whole-text rule
  const hit = new Map();
  let total = 0;
  for (const c of cases({ sparse: false })) {
    total += 1;
    if (c.place !== 'bare') continue;
    if (refReason(c.text) !== null) hit.set(c.family, (hit.get(c.family) || 0) + 1);
  }
  for (const f of FAMILIES) assert.ok((hit.get(f.id) || 0) >= (f.fixed ? 2 : 100), `${f.id}: the reference withholds ${hit.get(f.id) || 0} bare texts of the sweep`);
  const targeted = new Set(FAMILIES.map((f) => f.rule).filter(Boolean));
  for (const r of REF_RULES) assert.ok(targeted.has(r.reason), `${r.reason}: a family is about it`);
  assert.ok(total > 40000, `${total} dense cases`);
});

test('AC10 [r8] DIFFERENTIAL (the whole read): whatever the round-6 rules withhold, the card still withholds, in every family, at every length from 1 to 300, 400, 600 and 1000, and at both sides of every bound, in every place', () => {
  let n = 0;
  let refHits = 0;
  const lost = [];
  for (const c of cases()) {
    n += 1;
    if (refReason(c.text) === null) continue;
    refHits += 1;
    if (redactValue(c.text, { key: 'note' }) !== WITHHELD) lost.push(c);
    else if (n % 5 === 0 && redactValue(c.text) !== WITHHELD) lost.push({ ...c, family: `${c.family} (no key)` });
  }
  console.log(`differential, whole read: ${n} texts, the round-6 rules withhold ${refHits}, the card withholds all of them (${lost.length} lost)`);
  assert.ok(n > 50000 && refHits > 30000, `${n} texts, ${refHits} withheld by the reference`);
  assert.deepEqual(lost.slice(0, 8).map(label), [], `${lost.length} texts that round 6 withheld are SHOWN`);
});

test('AC10 [r8] DIFFERENTIAL (rule by rule): for every one of the 23 rules, a text the round-6 rule matches is matched by the card\'s rule of the same name (a rule that lost a match is named even where another rule would still withhold the text)', () => {
  let n = 0;
  let ruleHits = 0;
  const lost = [];
  const byRule = {};
  for (const c of cases({ sparse: true })) {
    if (c.place === 'middle' || c.place === 'end' || !ASCII.test(c.text)) continue;
    n += 1;
    for (const ref of REF_RULES) {
      if (!refRuleHits(ref, c.text)) continue;
      ruleHits += 1;
      byRule[ref.reason] = (byRule[ref.reason] || 0) + 1;
      if (!cardRuleHits(cardRule(ref.reason), c.text)) lost.push({ ...c, family: `${ref.reason} <- ${c.family}` });
    }
  }
  console.log(`differential, rule by rule: ${n} texts, ${ruleHits} rule matches of the reference, ${lost.length} lost; ${JSON.stringify(byRule)}`);
  assert.equal(Object.keys(byRule).length, 23, `every one of the 23 rules is exercised: ${JSON.stringify(byRule)}`);
  assert.deepEqual(lost.slice(0, 8).map(label), [], `${lost.length} rule matches of round 6 are lost`);
});

test('AC10 [r8] the gate can see the class: the round-7 bounded forms of the six rules LOSE texts on this corpus (negative controls), each for the reason a bound gives', () => {
  const lostBy = {};
  const first = {};
  for (const c of cases({ sparse: true })) {
    if (c.place === 'middle' || c.place === 'end' || !ASCII.test(c.text)) continue;
    for (const [reason, re] of Object.entries(R7)) {
      const ref = refRule(reason);
      if (!refRuleHits(ref, c.text)) continue;
      if (!refRuleHits({ ...ref, pattern: re }, c.text)) {
        lostBy[reason] = (lostBy[reason] || 0) + 1;
        first[reason] = first[reason] || label(c);
      }
    }
  }
  for (const reason of Object.keys(R7)) assert.ok((lostBy[reason] || 0) >= (reason === 'MAC address (dotted)' ? 5 : 20), `${reason}: the round-7 form loses ${lostBy[reason] || 0} texts`);
  console.log(`round-7 forms lose: ${JSON.stringify(lostBy)}; first: ${JSON.stringify(first)}`);
});

test('AC10 [r8] the reviewer\'s five inputs, named: each was withheld in round 6, SHOWN in round 7, and is withheld now (whole read, with and without a key, and under a revision key)', () => {
  const j = (...p) => p.join('');
  const text = {
    'a token parameter name of 65 characters before the key word (a real secret value was shown)': j('https://e.org/x?', 'p'.repeat(65), '_token=s3cr3tvalue'),
    'a token parameter name of 65 characters after the key word': j('https://e.org/x?token_', 'p'.repeat(65), '=s3cr3tvalue'),
    'a connection pair after a bracket with a value of 300 characters (uid)': j('(uid=', 'jsmith'.repeat(50), ';)'),
    'a connection pair after a comma with a value of 300 characters (host)': j('x,host=', 'srv'.repeat(100), ';'),
    'a JWT whose first segment is over 512 characters and has no digit run': j('eyJ', 'abcdefgh-'.repeat(67), '.', 'abcdefgh-'.repeat(5), '.sig'),
    'a JWT whose second segment is over 4096 characters and has no digit run': j('eyJ', 'abcdefgh-'.repeat(5), '.', 'abcdefgh-'.repeat(520), '.sig'),
    'a key block with a label of 80 characters': j('-----BEGIN ', 'OPENSSH PRIVATE KEY '.repeat(4), '-----'),
    'a webhook on a host name of 260 characters (letters that no other rule reads)': j('https://hooks.', 'g'.repeat(260), '.com/services/T0000/B0000/XXXXXXXXXXXX'),
    'an address in the dotted form with a letter after it (2026.1114.0900.beef)': j('2026.1114.0900', '.beef'),
  };
  for (const [what, t] of Object.entries(text)) {
    assert.notEqual(refReason(t), null, `round 6 withheld ${what}`);
    assert.equal(redactValue(t, { key: 'note' }), WITHHELD, what);
    assert.equal(redactValue(t), WITHHELD, `${what} (no key)`);
    assert.equal(redactValue(t, { key: 'git_sha' }), WITHHELD, `${what} (revision key)`);
    assert.equal(redactValue({ a: [t] }).a[0], WITHHELD, `${what} (in a list)`);
  }
});
