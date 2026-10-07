// Pure-core tests: parser, decoders, masks, derivation for every scenario, countdown, register table, checks.
import test from 'node:test';
import assert from 'node:assert/strict';
import { card, scenarios, meta, IDS, T0, build, renderScenario, textNodes } from './helpers.mjs';

const {
  parseKv, parseU, parseHex, parseSlotTuple, parseSlotsEntity, parseContextEntity, KV_KEYS, isAvailable,
  maskBit, popcount, regDiff, regDiffAny, DX_BITS, DC_BITS, DI_BITS,
  parseObl, oblKindClass, parseLatch, parseSv, parseB9, b9Tone,
  dec244, dec243, decSrc, modeText, hhmmText, hhmmValid, formatWord, ringValid, decodeWord, bit0,
  blockerText, warningRows, WARNING_TEXT, unusableSentence, untrustedSentence, notComparedNote, savedSegmentNote, SENTENCE,
  deriveModel, readEntities, makeAnchor, remainingSeconds, ageSeconds, countdownBucket, timeView, timeTexts,
  REGS, wordsFrom, buildRegisterTable, buildChecks, reviewButtonState, liveMatch,
  resolveDetail, readLocalDetail, writeLocalDetail, copyToClipboard,
  validateConfig, buildServiceCall, isAllowedServiceCall, fillTime,
} = card;

// ---------------------------------------------------------------------------
// parser
// ---------------------------------------------------------------------------
test('parseKv: well-formed strings, trailing semicolon, first = splits', () => {
  assert.deepEqual(parseKv('a=1;b=x=y;c=-'), { a: '1', b: 'x=y', c: '-' });
  assert.deepEqual(parseKv('a=1;b=2;'), { a: '1', b: '2' });
  assert.deepEqual(parseKv('st=IDLE', ['st']), { st: 'IDLE' });
});

test('parseKv: rejects non-strings, empty, over 200 chars, bad parts, duplicate keys, missing keys', () => {
  for (const bad of [undefined, null, 5, {}, '', ';', 'abc', '=1', 'a=', 'a=1;;b=2', 'a=1;a=2', 'a b=1', 'a=1;b']) {
    assert.equal(parseKv(bad), null, JSON.stringify(bad));
  }
  assert.equal(parseKv('a=1', ['a', 'b']), null);
  const long = `k=${'x'.repeat(198)}`;
  assert.equal(long.length, 200);
  assert.deepEqual(parseKv(long), { k: 'x'.repeat(198) });
  assert.equal(parseKv(`${long}x`), null, '201 characters is rejected');
});

test('parseKv: prototype-looking keys never pollute', () => {
  assert.equal(parseKv('__proto__=1'), null);
  assert.equal(parseKv('constructor=1;toString=2')?.constructor, '1');
  assert.equal(({}).polluted, undefined);
});

test('parseU / parseHex / isAvailable', () => {
  assert.equal(parseU('0'), 0);
  assert.equal(parseU('4294967295'), 4294967295);
  assert.equal(parseU('4294967296'), null);
  assert.equal(parseU('-1'), null);
  assert.equal(parseU('1.5'), null);
  assert.equal(parseU('70000', 65535), null);
  assert.equal(parseHex('00FF'), 255);
  assert.equal(parseHex('-'), null);
  assert.equal(parseHex('xyz'), null);
  for (const s of ['unavailable', 'unknown', '', undefined, null]) assert.equal(isAvailable(s), false);
  assert.equal(isAvailable('VALID'), true);
});

test('slot tuple: four decimal fields, HHMM is %04u (5 digits allowed), SRC is the full word', () => {
  assert.deepEqual(parseSlotTuple('0530/500/20/0'), { hhmm: 530, w: 500, soc: 20, src: 0 });
  assert.deepEqual(parseSlotTuple('2345/8000/100/65535'), { hhmm: 2345, w: 8000, soc: 100, src: 65535 });
  assert.deepEqual(parseSlotTuple('65535/65535/65535/65535'), { hhmm: 65535, w: 65535, soc: 65535, src: 65535 });
  for (const bad of ['-', '530/500/20/0', '0530/500/20', '0530/500/20/0/1', '0530/x/20/0', '65536/1/1/1', '', null, 5]) {
    assert.equal(parseSlotTuple(bad), null, String(bad));
  }
});

test('slots / context entities: grammar keys are all required; B7/B8 also need b', () => {
  const s = scenarios.ready_diff;
  assert.ok(parseSlotsEntity(s.review_slots, false));
  assert.equal(parseSlotsEntity(s.saved_slots, false)?.b, null, 'b is only read for saved views');
  const b8hex = /;b=([0-9A-F]{8})$/.exec(s.saved_slots)[1];
  assert.equal(parseSlotsEntity(s.saved_slots, true).b, b8hex);
  assert.equal(parseSlotsEntity(s.review_slots, true), null, 'a candidate string has no b key');
  assert.equal(parseSlotsEntity(s.saved_slots.replace(`;b=${b8hex}`, ''), true), null);
  assert.ok(parseContextEntity(s.review_context, false));
  assert.equal(parseContextEntity(s.saved_context, true).b, b8hex, 'B7 and B8 carry the same b');
  assert.equal(parseContextEntity(s.review_context, true), null);
  const none = parseSlotsEntity(scenarios.not_captured.review_slots, false);
  assert.equal(none.v, 'NONE');
  assert.deepEqual(none.slots, [null, null, null, null, null, null]);
  assert.equal(none.reg244, null);
  const ctx = parseContextEntity(s.review_context, false);
  assert.equal(ctx.r232, 1);
  assert.equal(ctx.r243, 1);
  assert.equal(ctx.r247, 1);
  assert.equal(ctx.r230, 185);
  assert.equal(ctx.ring, 'OK');
  assert.deepEqual(KV_KEYS.summary.length, 11);
  assert.deepEqual([...KV_KEYS.review], ['st', 'prior', 'exp', 'warn', 'obl', 'latch', 'sv']);
});

// ---------------------------------------------------------------------------
// decoders
// ---------------------------------------------------------------------------
test('register decoders follow design 4.2', () => {
  assert.equal(dec244(0), 'Allow Export');
  assert.equal(dec244(1), 'Essentials');
  assert.equal(dec244(2), 'Zero Export');
  assert.equal(dec244(9), 'unrecognised (9)');
  assert.equal(dec243(0), 'Battery First');
  assert.equal(dec243(1), 'Load First');
  assert.equal(dec243(2), 'unrecognised (2)');
  assert.deepEqual(['None', 'Grid', 'Generator', 'Grid + Generator'].map((_, i) => decSrc(i).src), ['None', 'Grid', 'Generator', 'Grid + Generator']);
  assert.deepEqual(decSrc(0), { src: 'None', mode: 'None', raw: null });
  assert.deepEqual(decSrc(1), { src: 'Grid', mode: 'None', raw: null });
  assert.equal(decSrc(4).mode, 'General');
  assert.equal(decSrc(8).mode, 'Backup');
  assert.equal(decSrc(16).mode, 'Charge');
  assert.equal(decSrc(5).mode, 'General');
  assert.equal(decSrc(5).src, 'Grid');
  // anything undecoded is shown raw beside the decoded text
  assert.equal(modeText(decSrc(0x20)), 'None raw 0x0020');
  assert.equal(modeText(decSrc(0x0c)), 'unrecognised raw 0x000C');
  assert.equal(modeText(decSrc(0x0104)), 'General raw 0x0104');
  assert.equal(decSrc(3).src, 'Grid + Generator');
});

test('HH:MM, register word formatting, 24 h ring', () => {
  assert.equal(hhmmText(0), '00:00');
  assert.equal(hhmmText(530), '05:30');
  assert.equal(hhmmText(2359), '23:59');
  assert.equal(hhmmText(2400), '2400 (invalid)');
  assert.equal(hhmmText(1060), '1060 (invalid)');
  assert.equal(hhmmText(1059), '10:59');
  assert.equal(hhmmText(null), '—');
  assert.equal(hhmmValid(2360), false);
  assert.equal(hhmmValid(1260), false);
  assert.equal(formatWord(232, 1), '0x0001');
  assert.equal(formatWord(248, 0), '0x0000');
  assert.equal(formatWord(247, 65535), '0xFFFF');
  assert.equal(formatWord(243, 1), '1');
  assert.equal(formatWord(257, undefined), '—');
  assert.equal(ringValid([0, 530, 900, 1600, 1900, 2345]), true);
  assert.equal(ringValid([0, 530, 530, 1600, 1900, 2345]), false, 'duplicate start');
  assert.equal(ringValid([0, 900, 530, 1600, 1900, 2345]), false, 'out of order');
  assert.equal(ringValid([0, 530, 900, 1600, 1900, 2460]), false, 'undecodable');
  assert.equal(bit0(1), true);
  assert.equal(bit0(0x0002), false);
  assert.equal(bit0(null), null);
});

test('decodeWord covers every register class', () => {
  assert.equal(decodeWord(244, 2), 'Zero Export');
  assert.equal(decodeWord(243, 0), 'Battery First');
  assert.equal(decodeWord(256, 8000), '8000 W');
  assert.equal(decodeWord(268, 20), '20 %');
  assert.equal(decodeWord(274, 1), 'Grid / None');
  assert.equal(decodeWord(250, 530), '05:30');
  assert.equal(decodeWord(232, 1), 'grid charging on');
  assert.equal(decodeWord(248, 0), 'TOU schedule off');
  assert.equal(decodeWord(247, 1), 'solar export on');
  assert.equal(decodeWord(230, 185), '185 A');
  assert.equal(decodeWord(245, 8000), '8000');
  assert.equal(decodeWord(244, undefined), '');
});

// ---------------------------------------------------------------------------
// masks
// ---------------------------------------------------------------------------
test('dx bit layout: bit0 244, bits1-6 256-261, bits7-12 268-273, bits13-18 274-279', () => {
  const expected = [244, 256, 257, 258, 259, 260, 261, 268, 269, 270, 271, 272, 273, 274, 275, 276, 277, 278, 279];
  expected.forEach((reg, bit) => {
    const dx = (1 << bit).toString(16).toUpperCase().padStart(5, '0');
    const hit = REGS.filter((r) => regDiff(r.reg, dx, '000', '00').core === true).map((r) => r.reg);
    assert.deepEqual(hit, [reg], `dx bit ${bit}`);
  });
  assert.equal(DX_BITS, 0x7ffff);
  assert.equal(popcount('7FFFF', DX_BITS), 19);
  assert.equal(popcount('FFFFF', DX_BITS), 19, 'bits above the layout are ignored');
});

test('dc bit layout: bit0 232.b0, bit1 243, bit2 248.b0, bits3-8 250-255', () => {
  const expected = [232, 243, 248, 250, 251, 252, 253, 254, 255];
  expected.forEach((reg, bit) => {
    const dc = (1 << bit).toString(16).toUpperCase().padStart(3, '0');
    const hit = REGS.filter((r) => regDiff(r.reg, '00000', dc, '00').core === true).map((r) => r.reg);
    assert.deepEqual(hit, [reg], `dc bit ${bit}`);
  });
  assert.equal(DC_BITS, 0x1ff);
});

test('di bit layout: bit0 230, bit1 245, bit2 247, bit3 232 upper bits, bit4 248 upper bits', () => {
  const expected = [230, 245, 247, 232, 248];
  expected.forEach((reg, bit) => {
    const di = (1 << bit).toString(16).toUpperCase().padStart(2, '0');
    const hit = REGS.filter((r) => regDiff(r.reg, '00000', '000', di).info === true).map((r) => r.reg);
    assert.deepEqual(hit, [reg], `di bit ${bit}`);
    assert.equal(regDiff(reg, '00000', '000', di).core === true && reg !== 232 && reg !== 248 ? 'core' : 'ok', 'ok');
  });
  assert.equal(DI_BITS, 0x1f);
  // information-only registers never count as a core (live match) difference
  assert.equal(regDiff(230, '7FFFF', '1FF', '1F').core, null);
});

test('masks that are "-" mean not comparable, never "equal"', () => {
  assert.equal(maskBit('-', 0), null);
  assert.equal(maskBit(undefined, 0), null);
  assert.equal(regDiffAny(257, '-', '-', '-'), null);
  assert.equal(regDiffAny(257, '00000', '000', '00'), false);
  assert.equal(regDiffAny(257, '00004', '000', '00'), true);
  assert.equal(regDiffAny(232, '00000', '000', '08'), true, 'upper-bit difference of 232 is an information difference');
});

// ---------------------------------------------------------------------------
// obligation vector, latch, saveability, B9
// ---------------------------------------------------------------------------
test('obligation vector: six DOM:KIND entries, kind classes fail closed', () => {
  const v = parseObl('FP:CA,DP:CM,R4:CA,MT:CN,FS:CA,BUS:OK');
  assert.deepEqual(v.map((e) => e.d), ['FP', 'DP', 'R4', 'MT', 'FS', 'BUS']);
  assert.equal(parseObl('-'), null);
  assert.equal(parseObl('FP:CA,garbage'), null);
  assert.equal(parseObl('FP:C'), null);
  for (const k of ['CM', 'CA', 'CN', 'CR', 'OK']) assert.equal(oblKindClass(k), 'clear', k);
  for (const k of ['AC', 'ST', 'RR', 'PC', 'EN', 'IF']) assert.equal(oblKindClass(k), 'transient', k);
  for (const k of ['ON', 'CT', 'UR', 'MC', 'ML', 'DV', 'LK', 'NP', 'BL', 'BY', 'ZZ']) assert.equal(oblKindClass(k), 'lockout', k);
});

test('latch and sv grammars', () => {
  assert.deepEqual(parseLatch('-'), []);
  assert.deepEqual(parseLatch('FP,R4'), ['FP', 'R4']);
  assert.deepEqual(parseSv('-'), { kind: 'none', codes: [], more: 0 });
  assert.deepEqual(parseSv('OK'), { kind: 'ok', codes: [], more: 0 });
  assert.deepEqual(parseSv('NO:244X'), { kind: 'no', codes: ['244X'], more: 0 });
  assert.deepEqual(parseSv('NO:PWRL2,SRCG4'), { kind: 'no', codes: ['PWRL2', 'SRCG4'], more: 0 });
  assert.deepEqual(parseSv('NO:244X,PWRL1,PWRL2+4'), { kind: 'no', codes: ['244X', 'PWRL1', 'PWRL2'], more: 4 });
  for (const bad of ['NO:', 'NO:x', 'MAYBE', 'NO:A,,B', 'NO:244X+', undefined]) assert.equal(parseSv(bad).kind, 'invalid', String(bad));
});

test('blocker texts: every sv code, exact wording of design 5.4', () => {
  const slots = [
    { hhmm: 0, w: 8000, soc: 100, src: 1 },
    { hhmm: 530, w: 300, soc: 20, src: 0 },
    { hhmm: 900, w: 9000, soc: 100, src: 0 },
    { hhmm: 1600, w: 3000, soc: 120, src: 2 },
    { hhmm: 1900, w: 3000, soc: 20, src: 4 },
    { hhmm: 2461, w: 3000, soc: 20, src: 0x0120 },
  ];
  const ctx = { reg244: 0, reg243: 5, slots };
  assert.equal(blockerText('244X', ctx), 'Export mode is Allow Export: Fallback V1 can only save a Zero Export profile (244 = 2).');
  assert.equal(blockerText('244X', { reg244: 1 }), 'Export mode is Essentials: Fallback V1 can only save a Zero Export profile (244 = 2).');
  assert.equal(blockerText('244X', { reg244: 7 }), 'Export mode is unrecognised (7): Fallback V1 can only save a Zero Export profile (244 = 2).');
  assert.equal(blockerText('PWRL2', ctx), 'Slot 2 power 300 W is below the 500 W V1 minimum.');
  assert.equal(blockerText('PWRH3', ctx), "Slot 3 power 9000 W is above 8000 W (or above this site's configured ceiling).");
  assert.equal(blockerText('SOCH4', ctx), 'Slot 4 target SOC 120 % is above 100 %.');
  assert.equal(blockerText('SRCG4', ctx), 'Slot 4 source Generator / Grid + Generator is unsupported in V1.');
  assert.equal(blockerText('MODE5', ctx), 'Slot 5 mode General / Backup / Charge is unsupported in V1.');
  assert.equal(blockerText('BITS6', ctx), 'Slot 6 has undecoded bits 0x0120 set.');
  assert.equal(blockerText('HHMM6', ctx), 'Slot 6 start 2461 is not a valid HH:MM time.');
  assert.equal(blockerText('243X', ctx), 'Energy-management model 5 is not recognised (0 Battery First, 1 Load First).');
  // values the entities did not carry drop out instead of printing undefined
  assert.equal(blockerText('PWRL1', {}), 'Slot 1 power is below the 500 W V1 minimum.');
  assert.equal(blockerText('243X', {}), 'Energy-management model is not recognised (0 Battery First, 1 Load First).');
  assert.equal(blockerText('BITS1', {}), 'Slot 1 has undecoded bits set.');
  // RING is not an sv code (an invalid ring is warning W6): it is reported as unknown, never decoded
  assert.match(blockerText('RING', ctx), /not recognised by this card/);
  assert.match(blockerText('WAT9', ctx), /not recognised by this card/);
  for (const code of ['244X', 'PWRL1', 'PWRH2', 'SOCH3', 'SRCG4', 'MODE5', 'BITS6', 'HHMM1', '243X']) {
    assert.doesNotMatch(blockerText(code, ctx), /undefined|NaN|null/);
  }
});

test('warning texts W1-W6 are exact; W5 names the off-grid slots', () => {
  const slots = [0, 530, 903, 1600, 1907, 2345].map((hhmm) => ({ hhmm, w: 1, soc: 1, src: 0 }));
  assert.equal(WARNING_TEXT.W1, 'Looks like a Free Power overlay - confirm this is your normal setup.');
  // dtgp1: W2 follows the configured Dump ceiling (3000 W by default), so the text names no wattage.
  assert.equal(WARNING_TEXT.W2, 'All six slot powers are equal and no higher than the Dump to Grid ceiling - this resembles Dump to Grid residue; confirm.');
  assert.doesNotMatch(WARNING_TEXT.W2, /\d+ ?W\b/);
  assert.equal(WARNING_TEXT.W3, "TOU schedule (248) is OFF: this profile's slot settings are inactive on the inverter.");
  assert.equal(WARNING_TEXT.W4, 'Grid charging is globally disabled (232) while slots select Grid.');
  assert.equal(WARNING_TEXT.W6, 'Slot times are not a valid 24 h ring (duplicate or out-of-order start).');
  const rows = warningRows('W1,W5,W6', slots);
  assert.deepEqual(rows.map((r) => r.code), ['W1', 'W5', 'W5', 'W6']);
  assert.equal(rows[1].text, 'Slot 3 start 09:03 is off the 5-minute grid.');
  assert.equal(rows[2].text, 'Slot 5 start 19:07 is off the 5-minute grid.');
  assert.equal(warningRows('W5', []).length, 1, 'generic text when no slot can be named');
  assert.equal(warningRows('-', slots).length, 0);
  assert.match(warningRows('W9', slots)[0].text, /not recognised/);
});

test('B9 prefixes, mismatch register, read block, tone classes', () => {
  const kinds = {
    'No Fallback Profile action since boot': 'seed',
    'review in progress (read-only)': 'reading',
    'CANDIDATE READY - x': 'ready',
    'CANDIDATE NOT SAVEABLE - x': 'notsaveable',
    'REVIEW REFUSED - x': 'refused',
    'REVIEW NOT COMPLETED - x': 'notcompleted',
    'REVIEW EXPIRED - candidate expired (120 s); review again': 'expired',
    'REVIEW CLEARED - x': 'cleared',
    'INTERNAL - x': 'internal',
    // FB-B2: the Save / Invalidate families are classified (SAVED used to be "other" before the firmware could save)
    'save in progress - re-reading live configuration': 'saveprogress',
    'SAVED - known-good profile generation 8 saved (verified this boot)': 'saved',
    'SAVE REFUSED - x': 'saverefused',
    'SAVE NOT COMMITTED - storage refused the write (E102); nothing changed': 'savenotcommitted',
    'SAVE OUTCOME UNKNOWN - storage reported E105; reboot': 'saveunknown',
    'INVALIDATED - profile generation 7 is no longer usable (now INVALIDATED g8)': 'invalidated',
    'INVALIDATE REFUSED - inverter busy; try again': 'invalidaterefused',
    'INVALIDATE NOT COMMITTED - storage refused the write (E102)': 'invalidatenotcommitted',
    'INVALIDATE OUTCOME UNKNOWN - E105/E106': 'invalidateunknown',
    "REFUSED - unsupported action 'FOO'": 'actionrefused',
    'RESTORE REFUSED - not implemented in this firmware': 'actionrefused',
    'ACKNOWLEDGE REFUSED - not implemented in this firmware': 'actionrefused',
    'SAVEDX - not a prefix of the set': 'other',
    'saved - lower case is not the outcome': 'other',
    '': 'other',
  };
  for (const [text, kind] of Object.entries(kinds)) assert.equal(parseB9(text).kind, kind, text);
  const m = parseB9(scenarios.mismatch.last_result);
  assert.deepEqual(m.mismatch, { reg: 257, a: '8000', b: '5000' });
  assert.equal(m.detail.startsWith('live configuration changed during the read'), true);
  assert.equal(parseB9(scenarios.read_error.last_result).block, '241/53');
  assert.equal(parseB9('REVIEW NOT COMPLETED - no response reading registers 230/3').block, '230/3');
  assert.equal(parseB9(scenarios.bus_busy.last_result).busy, true);
  assert.equal(parseB9(scenarios.bus_busy.last_result).block, null);
  assert.equal(b9Tone('CANDIDATE READY - x'), 'ok');
  assert.equal(b9Tone('REVIEW REFUSED - x'), 'warn');
  assert.equal(b9Tone('REVIEW NOT COMPLETED - x'), 'warn');
  assert.equal(b9Tone('CANDIDATE NOT SAVEABLE - x'), 'warn');
  assert.equal(b9Tone('INTERNAL - x'), 'bad');
  assert.equal(b9Tone('REVIEW EXPIRED - x'), 'neutral');
  assert.equal(b9Tone('review in progress (read-only)'), 'neutral');
  assert.equal(b9Tone(undefined), 'neutral');
});

// ---------------------------------------------------------------------------
// derivation
// ---------------------------------------------------------------------------
test('every fixture scenario derives to the documented view model', () => {
  const names = Object.keys(scenarios);
  assert.ok(names.length >= 40, `expected the full scenario set, got ${names.length}`);
  assert.deepEqual(Object.keys(meta).sort(), names.slice().sort(), 'every scenario has expectations');
  for (const name of names) {
    const { vm, tv } = build(name);
    const e = meta[name].expect;
    assert.equal(vm.profile, e.profile, `${name}: profile`);
    assert.equal(vm.review, e.review, `${name}: review`);
    assert.equal(vm.hasCand, e.hasCand, `${name}: hasCand`);
    if ('eligible' in e) assert.equal(vm.eligible, e.eligible, `${name}: eligible`);
    if ('exp' in e) assert.equal(vm.exp, e.exp, `${name}: exp`);
    if ('live' in e) assert.equal(liveMatch(vm, tv).word, e.live, `${name}: live match`);
    if ('button' in e) assert.equal(reviewButtonState(vm).disabled, e.button === 'disabled', `${name}: button`);
    if ('dx' in e) assert.equal(vm.sl.dx, e.dx, `${name}: dx`);
    if ('dc' in e) assert.equal(vm.cx.dc, e.dc, `${name}: dc`);
    if ('di' in e) assert.equal(vm.cx.di, e.di, `${name}: di`);
    if ('mismatch' in e) assert.deepEqual(vm.mismatch, e.mismatch, `${name}: mismatch`);
    if ('block' in e) assert.equal(vm.b9.block, e.block, `${name}: block`);
    if ('blockers' in e) assert.equal(vm.blockers.length, e.blockers, `${name}: blockers`);
    if ('warnings' in e) assert.equal(vm.warnings.length, e.warnings, `${name}: warnings`);
    if ('notes' in e) assert.equal(vm.notes.length, e.notes, `${name}: notes`);
    if ('latch' in e) assert.deepEqual(vm.latch, e.latch, `${name}: latch`);
    if ('checkStates' in e) assert.deepEqual(buildChecks(vm, tv).map((c) => c.state), e.checkStates, `${name}: checks`);
    // FB-B2: the arm switch state and the card's own save gate ('allowed' means the arm is on and every prerequisite passes)
    if ('armState' in e) assert.equal(vm.arm.state, e.armState, `${name}: arm`);
    if ('save' in e) assert.equal(card.saveGate(vm, tv).allowed ? 'allowed' : 'blocked', e.save, `${name}: save gate`);
    if ('variant' in e) assert.equal(card.saveGate(vm, tv).variant, e.variant, `${name}: save variant`);
  }
});

test('B1 values map to the profile state (design 4.3)', () => {
  const E = (b1) => ({ ...scenarios.idle_saved, profile_state: b1 });
  const expect = {
    NOT_CAPTURED: 'notsaved', VALID: 'saved', INVALIDATED: 'invalidated', CORRUPT: 'unusable', CORRUPT_DOMAIN: 'unusable',
    UNREADABLE: 'unusable', PROFILE_LOST: 'unusable', SAVE_UNCONFIRMED: 'unusable', PROFILE_STALE: 'unusable',
  };
  assert.deepEqual(Object.keys(expect), [...card.CLASS_NAMES]);
  for (const [b1, profile] of Object.entries(expect)) assert.equal(deriveModel(E(b1), IDS).profile, profile, b1);
  for (const b1 of ['unavailable', 'unknown', '', undefined]) assert.equal(deriveModel(E(b1), IDS).profile, 'unavailable', String(b1));
  assert.equal(deriveModel(E('SOMETHING_NEW'), IDS).profile, 'unrecognised');
});

test('review state: B3 st first, then the B9 prefix while idle', () => {
  const base = scenarios.idle_saved;
  const idle = base.review;
  const withB9 = (b9) => deriveModel({ ...base, review: idle, last_result: b9 }, IDS).review;
  assert.equal(withB9('No Fallback Profile action since boot'), 'available');
  assert.equal(withB9('REVIEW REFUSED - x'), 'refused');
  assert.equal(withB9('REVIEW NOT COMPLETED - live configuration changed during the read (register 244: 2 then 1); x'), 'mismatch');
  assert.equal(withB9('REVIEW NOT COMPLETED - no response reading registers 230/3'), 'readerror');
  assert.equal(withB9('REVIEW EXPIRED - candidate expired (120 s); review again'), 'expired');
  assert.equal(withB9('REVIEW CLEARED - a temporary operation started (Free Power)'), 'cleared');
  assert.equal(withB9('INTERNAL - x'), 'internal');
  assert.equal(withB9('SAVED - from a later stage'), 'available');
  assert.equal(withB9('unavailable'), 'available');
  const st = (s, extra = '') => deriveModel({ ...base, review: `st=${s};prior=-;exp=${s.startsWith('CAND') ? 50 : '-'};warn=-;obl=-;latch=-;sv=-${extra}`, last_result: 'REVIEW REFUSED - stale' }, IDS).review;
  assert.equal(st('READING'), 'reading', 'READING wins over a stale B9');
  assert.equal(st('CANDIDATE_READY'), 'ready');
  assert.equal(st('CANDIDATE_NOT_SAVEABLE'), 'notsaveable');
  // FB-B2: SAVING is a status of its own; INVALIDATING (never published) and the reserved FB-E values stay unknown
  assert.equal(st('SAVING'), 'saving', 'SAVING wins over a stale B9, like READING');
  for (const unknown of ['INVALIDATING', 'PLAN_READY', 'PLAN_NOT_POSSIBLE', 'APPLYING', 'saving']) {
    assert.equal(st(unknown), 'unrecognised', `${unknown}: a status this card does not know is never guessed`);
  }
  assert.equal(deriveModel({ ...base, review: 'unknown' }, IDS).review, 'unavailable');
  assert.equal(deriveModel({ ...base, review: 'st=IDLE' }, IDS).reviewReason, 'malformed');
  assert.equal(deriveModel({ ...base, review: undefined }, IDS).reviewReason, 'absent');
});

test('derivation survives an empty / hostile entity set without throwing', () => {
  for (const E of [{}, { review: 5 }, { profile_state: null }, Object.fromEntries(Object.keys(IDS).map((k) => [k, '\u0000<script>']))]) {
    const vm = deriveModel(E, IDS);
    assert.equal(vm.review === 'unavailable' || vm.review === 'unrecognised' || vm.review === 'available', true);
    assert.equal(vm.hasCand, false);
  }
});

test('candidate blockers and notes come from sv, prior and the class (not from the mockup)', () => {
  const ns = build('not_saveable').vm;
  assert.deepEqual(ns.blockers, [
    'Slot 2 power 300 W is below the 500 W V1 minimum.',
    'Slot 4 source Generator / Grid + Generator is unsupported in V1.',
  ]);
  const un = build('not_saveable_unreadable').vm;
  assert.deepEqual(un.blockers, ['Stored profile is UNREADABLE: saving stays disabled until the dongle restarts.']);
  const corrupt = build('ready_corrupt_prior').vm;
  assert.equal(corrupt.eligible, true, 'the firmware verdict (READY) is authoritative, not the prior class');
  // FB-B2: saving exists now, so the note says what it does instead of "will need ... (FB-B2)"
  assert.deepEqual(corrupt.notes, ['Stored profile is CORRUPT: saving replaces it and needs the REPLACE CORRUPT confirmation.']);
  const many = build('not_saveable_many').vm;
  assert.equal(many.blockers.length, 4);
  assert.equal(many.blockers[3], '4 more reasons not listed (see technical detail).');
  assert.equal(build('ready_match').vm.blockers.length, 0);
});

test('B5/B6 are candidate-only and B7/B8 saved-only: a view of the wrong kind is not used', () => {
  const E = { ...scenarios.ready_match, review_slots: scenarios.ready_match.saved_slots.replace(/;b=.*$/, ''), review_context: scenarios.ready_match.saved_context.replace(/;b=.*$/, '') };
  assert.equal(deriveModel(E, IDS).candOK, false, 'v=SAVED in B5/B6 is not a candidate');
  const E2 = { ...scenarios.ready_match, saved_slots: scenarios.ready_match.review_slots + ';b=00000000', saved_context: scenarios.ready_match.review_context + ';b=00000000' };
  assert.equal(deriveModel(E2, IDS).savedOK, false, 'v=CAND in B7/B8 is not a saved profile');
});

test('readEntities reads state and last_changed through the configured ids', () => {
  const states = {
    [IDS.review]: { state: 'st=IDLE', last_changed: '2026-09-30T10:00:00.000Z' },
    [IDS.profile_state]: { state: 'VALID', last_changed: 'not a date' },
  };
  const { E, changed } = readEntities(IDS, states);
  assert.equal(E.review, 'st=IDLE');
  assert.equal(E.profile_state, 'VALID');
  assert.equal(E.summary, undefined);
  assert.equal(changed.review, Date.parse('2026-09-30T10:00:00.000Z'));
  assert.equal(changed.profile_state, null);
  // FB-B2: fifteen entities plus the arm and the three read-only write arms
  assert.deepEqual(Object.keys(readEntities(IDS, undefined).E).length, 19, 'nineteen entity keys');
});

// ---------------------------------------------------------------------------
// countdown (design 6)
// ---------------------------------------------------------------------------
test('countdown buckets at the design boundaries 0 / 14 / 15 / 45 / 46 / 120', () => {
  assert.equal(countdownBucket(120), 'plenty');
  assert.equal(countdownBucket(46), 'plenty');
  assert.equal(countdownBucket(45), 'soon');
  assert.equal(countdownBucket(15), 'soon');
  assert.equal(countdownBucket(14), 'urgent');
  assert.equal(countdownBucket(1), 'urgent');
  assert.equal(countdownBucket(0), 'zero');
  assert.equal(countdownBucket(null), null);
});

test('remaining time is derived from exp and the publish time and never rounded up', () => {
  const a = makeAnchor({ exp: 45, lastChangedMs: T0, receivedMs: T0, nowMs: T0 });
  assert.deepEqual(a, { exp: 45, at: T0 });
  assert.equal(remainingSeconds(a, T0), 45);
  assert.equal(remainingSeconds(a, T0 + 1), 44, 'a fraction of a second already consumed is not shown as a whole second left');
  assert.equal(remainingSeconds(a, T0 + 1000), 44);
  assert.equal(remainingSeconds(a, T0 + 1001), 43);
  assert.equal(remainingSeconds(a, T0 + 44_000), 1);
  assert.equal(remainingSeconds(a, T0 + 44_001), 0, 'under one second left is "expiring", not "0:01"');
  assert.equal(remainingSeconds(a, T0 + 45_000), 0);
  assert.equal(remainingSeconds(a, T0 + 999_000), 0, 'never negative');
  assert.equal(remainingSeconds(a, T0 - 5000), 45, 'a clock that moved backwards never extends the countdown');
  assert.equal(remainingSeconds(null, T0), null);
  const full = makeAnchor({ exp: 120, lastChangedMs: T0, nowMs: T0 });
  assert.equal(timeTexts(timeView(full, T0)).rem, '2:00');
  assert.equal(timeTexts(timeView(full, T0 + 1)).rem, '1:59');
});

test('zero shows "expiring…" (the firmware has not confirmed), never "0:00"', () => {
  const a = makeAnchor({ exp: 3, lastChangedMs: T0, nowMs: T0 });
  assert.equal(timeTexts(timeView(a, T0 + 60_000)).rem, 'expiring…');
  assert.equal(timeView(a, T0 + 60_000).bucket, 'zero');
  for (let s = 0; s < 200; s++) assert.notEqual(timeTexts(timeView(a, T0 + s * 1000)).rem, '0:00');
  const e0 = makeAnchor({ exp: 0, lastChangedMs: T0, nowMs: T0 });
  assert.equal(timeTexts(timeView(e0, T0)).rem, 'expiring…');
});

test('anchors: invalid exp, future last_changed (browser clock behind), missing last_changed', () => {
  for (const exp of [-1, 121, 3.5, NaN, null, undefined, '5']) assert.equal(makeAnchor({ exp, lastChangedMs: T0, nowMs: T0 }), null, String(exp));
  assert.equal(makeAnchor({ exp: 50, lastChangedMs: T0 + 30_000, nowMs: T0 }).at, T0, 'future publish time is clamped to now');
  assert.equal(makeAnchor({ exp: 50, lastChangedMs: null, receivedMs: T0 - 2000, nowMs: T0 }).at, T0 - 2000);
  assert.equal(makeAnchor({ exp: 50, lastChangedMs: NaN, receivedMs: undefined, nowMs: T0 }).at, T0);
});

test('resync: a new firmware publish snaps the countdown both ways (larger and smaller)', () => {
  const first = makeAnchor({ exp: 80, lastChangedMs: T0, nowMs: T0 });
  assert.equal(remainingSeconds(first, T0 + 9500), 70);
  const smaller = makeAnchor({ exp: 69, lastChangedMs: T0 + 10_000, nowMs: T0 + 10_000 });
  assert.equal(remainingSeconds(smaller, T0 + 10_000), 69, 'snapped down by the 1 s of drift');
  const larger = makeAnchor({ exp: 75, lastChangedMs: T0 + 10_000, nowMs: T0 + 10_000 });
  assert.equal(remainingSeconds(larger, T0 + 10_000), 75, 'snapped up');
});

test('age and remaining always add up to 2:00; created time is the anchor minus what was consumed', () => {
  const a = makeAnchor({ exp: 87, lastChangedMs: T0, nowMs: T0 });
  for (const ms of [0, 1, 400, 999, 1000, 1001, 33_333, 86_999]) {
    const tv = timeView(a, T0 + ms);
    assert.equal(tv.rem + tv.age, 120, `elapsed ${ms} ms`);
  }
  assert.equal(timeView(a, T0).createdMs, T0 - 33_000);
  assert.equal(timeView(a, T0 + 50_000).createdMs, T0 - 33_000, 'created does not move');
  assert.equal(timeView(null, T0).has, false);
  assert.equal(timeView(a, T0).pct, 87 / 120 * 100);
});

// ---------------------------------------------------------------------------
// register table (design 5.7 pass rule)
// ---------------------------------------------------------------------------
test('REGS is the Fallback Profile struct order, 31 rows with classes', () => {
  const range = (a, b) => Array.from({ length: b - a + 1 }, (_, i) => a + i);
  const order = [244, ...range(256, 261), ...range(268, 273), ...range(274, 279), 232, 243, 248, ...range(250, 255), 230, 245, 247];
  assert.equal(order.length, 31);
  assert.deepEqual(REGS.map((r) => r.reg), order);
  const cls = Object.fromEntries(REGS.map((r) => [r.reg, r.cls]));
  for (const r of [244, ...range(256, 261), ...range(268, 273), ...range(274, 279)]) assert.equal(cls[r], 'E1', String(r));
  for (const r of [232, 243, 248, ...range(250, 255)]) assert.equal(cls[r], 'CTX', String(r));
  for (const r of [230, 245, 247]) assert.equal(cls[r], 'INFO', String(r));
  assert.equal(new Set(REGS.map((r) => r.name)).size, 31, 'friendly names are unique');
});

test('pass columns: candidate state shows the agreed word in both passes, nothing else is invented', () => {
  const t = buildRegisterTable(build('ready_diff').vm);
  assert.equal(t.mode, 'candidate');
  assert.equal(t.rows.length, 31);
  assert.equal(t.caption, 'Pass 1 and pass 2 agreed on all 31 registers; the firmware publishes the agreed words once.');
  for (const r of t.rows) {
    assert.equal(r.p1, r.p2, `${r.reg}: both passes carry the one published word`);
    assert.equal(r.match, 'ok', String(r.reg));
    assert.notEqual(r.p1, '—');
  }
  const r257 = t.rows.find((r) => r.reg === 257);
  assert.deepEqual([r257.p1, r257.p2, r257.saved, r257.delta, r257.decoded], ['5000', '5000', '500', 'ne', '5000 W']);
  assert.equal(t.rows.find((r) => r.reg === 258).delta, 'eq');
  assert.equal(t.rows.find((r) => r.reg === 232).p1, '0x0001');
  assert.equal(t.rows.find((r) => r.reg === 230).delta, 'ne', 'di bit0');
  assert.equal(t.rows.find((r) => r.reg === 277).delta, 'ne', 'dx bit 16');
  assert.equal(t.savedLabel, 'Saved g7');
});

test('pass columns: not-saveable candidates still show the agreed words', () => {
  const t = buildRegisterTable(build('not_saveable').vm);
  assert.equal(t.mode, 'candidate');
  assert.equal(t.rows.find((r) => r.reg === 257).p1, '300');
});

test('pass columns: a mismatch fills only the register the firmware named', () => {
  const t = buildRegisterTable(build('mismatch').vm);
  assert.equal(t.mode, 'mismatch');
  assert.equal(t.caption, 'The firmware reports the first differing register only.');
  for (const r of t.rows) {
    if (r.reg === 257) {
      assert.deepEqual([r.p1, r.p2, r.match], ['8000', '5000', 'bad']);
    } else {
      assert.deepEqual([r.p1, r.p2, r.match], ['—', '—', 'none'], String(r.reg));
    }
    assert.equal(r.delta, 'none', 'no comparison outside a candidate');
  }
  assert.equal(t.rows.find((r) => r.reg === 257).saved, '500', 'the saved column stays populated');
});

test('pass columns: every other state leaves both pass columns empty', () => {
  for (const name of ['idle_saved', 'reading', 'read_error', 'refused', 'expired', 'cleared', 'internal', 'unavailable', 'not_captured', 'unusable', 'bus_busy']) {
    const t = buildRegisterTable(build(name).vm);
    assert.equal(t.mode, 'none', name);
    assert.equal(t.caption, 'No review values to show.');
    for (const r of t.rows) assert.deepEqual([r.p1, r.p2, r.match, r.delta], ['—', '—', 'none', 'none'], `${name} ${r.reg}`);
  }
  const saved = buildRegisterTable(build('idle_saved').vm);
  assert.equal(saved.rows.find((r) => r.reg === 244).saved, '2');
  assert.equal(saved.rows.find((r) => r.reg === 244).decoded, 'Zero Export');
  const none = buildRegisterTable(build('not_captured').vm);
  assert.ok(none.rows.every((r) => r.saved === '—'));
});

test('no saved profile: a candidate is shown without any delta (dx is "-", not "equal")', () => {
  const t = buildRegisterTable(build('not_captured_cand').vm);
  assert.equal(t.mode, 'candidate');
  assert.ok(t.rows.every((r) => r.delta === 'none'));
  const corrupt = buildRegisterTable(build('ready_corrupt_prior').vm);
  assert.ok(corrupt.rows.every((r) => r.delta === 'none'));
});

test('wordsFrom collects every register of a parsed pair', () => {
  const vm = build('ready_diff').vm;
  const w = wordsFrom(vm.sl, vm.cx);
  assert.equal(Object.keys(w).length, 31);
  assert.equal(w[257], 5000);
  assert.equal(w[250], 0);
  assert.equal(w[255], 2345);
  assert.equal(w[232], 1);
  assert.deepEqual(wordsFrom(null, null), {});
});

// ---------------------------------------------------------------------------
// save-readiness checks and the review button
// ---------------------------------------------------------------------------
test('checks 5 and 6 (supervision, NTP) are save prerequisites only: they never gate the Review button', () => {
  const vm = build('ready_nosup').vm;
  const tv = build('ready_nosup').tv;
  const checks = buildChecks(vm, tv);
  assert.equal(checks[4].state, 'fail');
  assert.equal(checks[5].state, 'fail');
  assert.equal(reviewButtonState(vm).disabled, false);
  for (const name of ['idle_saved', 'ready_nosup', 'read_error']) {
    const v = { ...build(name).vm, sup: { stable: false, state: 'LOST' }, ntp: false };
    assert.equal(reviewButtonState(v).disabled, false, name);
  }
});

test('check labels, order and the six rows', () => {
  const { vm, tv } = build('ready_match');
  const checks = buildChecks(vm, tv);
  assert.deepEqual(checks.map((c) => c.label), [
    'Both read passes identical',
    'Profile values valid for Fallback V1',
    'Candidate not expired',
    'No temporary operation active',
    'Supervision stable',
    'Trusted time',
  ]);
  assert.deepEqual(checks.map((c) => c.n), [1, 2, 3, 4, 5, 6]);
  assert.deepEqual(checks.map((c) => c.state), ['pass', 'pass', 'pass', 'pass', 'pass', 'pass']);
});

test('check 3 follows the countdown buckets; check 4 follows the obligation vector', () => {
  const at = (name, s) => buildChecks(build(name, { elapsedS: s }).vm, build(name, { elapsedS: s }).tv);
  assert.equal(at('ready_expiring', 0)[2].state, 'warn');
  assert.match(at('ready_expiring', 0)[2].detail, /expiring soon/);
  assert.equal(at('ready_expiring', 12)[2].state, 'fail');
  assert.equal(at('ready_diff', 0)[2].state, 'pass');
  assert.equal(at('ready_diff', 66)[2].state, 'pass');
  assert.equal(at('ready_diff', 67)[2].state, 'warn', '45 s left is already "expiring soon" (same bucket as the countdown)');
  assert.equal(at('idle_saved', 0)[3].state, 'unknown');
  assert.equal(at('idle_saved', 0)[3].detail, 'Checked at Review');
  assert.equal(at('transient_op', 0)[3].state, 'warn');
  assert.equal(at('refused', 0)[3].state, 'fail');
  assert.match(at('refused', 0)[3].detail, /Free Power is running/);
  assert.equal(at('refused_lock', 0)[3].state, 'fail');
  assert.equal(at('refused_latch', 0)[3].state, 'fail');
  assert.equal(at('expired', 0)[2].state, 'fail');
  assert.equal(at('mismatch', 0)[0].state, 'fail');
  assert.equal(at('reading', 0)[0].state, 'pending');
  assert.equal(at('unavailable', 0).every((c) => c.state === 'unknown'), true);
});

test('check 2: blockers fail, warnings warn, clean passes', () => {
  assert.equal(buildChecks(build('not_saveable').vm, build('not_saveable').tv)[1].state, 'fail');
  assert.equal(buildChecks(build('ready_warn').vm, build('ready_warn').tv)[1].state, 'warn');
  assert.equal(buildChecks(build('ready_warn').vm, build('ready_warn').tv)[1].detail, '4 warnings - see candidate');
  assert.equal(buildChecks(build('ready_w1').vm, build('ready_w1').tv)[1].detail, '1 warning - see candidate');
  assert.equal(buildChecks(build('ready_match').vm, build('ready_match').tv)[1].state, 'pass');
});

test('Review button is disabled (still focusable) exactly in the documented cases', () => {
  const dis = (name, o) => reviewButtonState(build(name).vm, o);
  assert.deepEqual(dis('idle_saved'), { disabled: false, why: '' });
  assert.deepEqual(dis('reading'), { disabled: true, why: 'Review in progress' });
  assert.deepEqual(dis('unavailable'), { disabled: true, why: 'Entities unavailable' });
  assert.deepEqual(dis('partial_unavailable'), { disabled: true, why: 'Entities unavailable' });
  assert.deepEqual(dis('refused_lock'), { disabled: true, why: 'Inverter bus busy - try again shortly' });
  assert.deepEqual(dis('st_unrecognised'), { disabled: true, why: 'Review status not recognised' });
  assert.deepEqual(dis('button_unavailable'), { disabled: true, why: 'Review button unavailable' });
  assert.deepEqual(dis('idle_saved', { pending: true }), { disabled: true, why: 'Review requested' });
  // a button entity that was never pressed reports "unknown": that is normal and must stay enabled
  assert.equal(scenarios.idle_saved.review_button, 'unknown');
  assert.equal(dis('idle_saved').disabled, false);
  // candidates, refusals and read errors can all be reviewed again
  for (const n of ['ready_diff', 'not_saveable', 'mismatch', 'read_error', 'refused', 'expired', 'cleared', 'internal', 'config_offline']) {
    assert.equal(dis(n).disabled, false, n);
  }
});

test('live match: precedence of design 4.3', () => {
  const lm = (name, s = 0) => liveMatch(build(name, { elapsedS: s }).vm, build(name, { elapsedS: s }).tv);
  assert.equal(lm('unavailable').word, 'NOT REPORTING');
  assert.equal(lm('partial_unavailable').word, 'NOT REPORTING');
  assert.equal(lm('not_captured').word, 'UNKNOWN');
  assert.equal(lm('not_captured').sentence[0], 'No saved profile to compare against.');
  assert.equal(lm('invalidated').word, 'UNKNOWN');
  assert.equal(lm('unusable').word, 'UNKNOWN');
  assert.equal(lm('reading').word, 'CHECKING');
  assert.equal(lm('idle_saved').word, 'UNKNOWN');
  assert.equal(lm('idle_saved').sentence[0], 'Press Review Current Configuration to compare. Live comparison without a review arrives in FB-B3.');
  assert.equal(lm('ready_match').word, 'MATCHES SAVED PROFILE');
  assert.equal(lm('ready_diff').word, 'DIFFERS');
  assert.equal(lm('ready_ctx_diff').word, 'DIFFERS (CONTEXT)');
  assert.deepEqual(lm('ready_diff').chips, ['Slot 2 power', 'Slot 4 source / mode']);
  assert.equal(lm('ready_match').chips.length, 0);
  assert.match(lm('ready_info_diff').sentence.join(''), /Info-only values differ \(not restored by Fallback V1\)\.$/);
  assert.match(lm('ready_diff').sentence[0], /in 2 places \(as of the review $/);
  assert.match(lm('ready_ctx_diff').sentence[0], /^Slot times or context differ from the saved profile in 1 place \(/);
  assert.equal(lm('expired').word, 'UNKNOWN', 'no candidate -> unknown, never a pretended continuous match');
  assert.equal(lm('mismatch').word, 'UNKNOWN');
  assert.equal(lm('not_captured_cand').word, 'UNKNOWN');
  const many = lm('not_saveable_many');
  assert.equal(many.chips.length, 3);
  assert.equal(many.names.length, 7, 'export mode plus six slot powers');
  assert.equal(many.more, 4);
  assert.equal(lm('ready_warn').names.length, 7);
  assert.equal(lm('ready_warn').more, 4);
  assert.equal(lm('ready_warn').chips.length, 3);
});

// ---------------------------------------------------------------------------
// technical detail toggle, clipboard, configuration, service calls
// ---------------------------------------------------------------------------
test('technical detail: helper wins when it reports on/off; local storage is guarded everywhere', () => {
  assert.equal(resolveDetail({ helperState: 'on', local: false }), true);
  assert.equal(resolveDetail({ helperState: 'off', local: true }), false);
  assert.equal(resolveDetail({ helperState: null, local: true }), true);
  assert.equal(resolveDetail({ helperState: null, local: false }), false);
  assert.equal(resolveDetail({ helperState: 'unavailable', local: true }), true);
  const mem = new Map();
  const ok = { getItem: (k) => mem.get(k) ?? null, setItem: (k, v) => mem.set(k, v) };
  assert.equal(readLocalDetail(ok), false);
  assert.equal(writeLocalDetail(true, ok), true);
  assert.equal(readLocalDetail(ok), true);
  assert.equal(writeLocalDetail(false, ok), true);
  assert.equal(readLocalDetail(ok), false);
  const throwing = { getItem() { throw new Error('SecurityError'); }, setItem() { throw new Error('QuotaExceededError'); } };
  assert.equal(readLocalDetail(throwing), false);
  assert.equal(writeLocalDetail(true, throwing), false);
  assert.equal(readLocalDetail(null), false);
  assert.equal(writeLocalDetail(true, null), false);
  // no localStorage global at all (node): the default accessor must not throw either
  assert.equal(readLocalDetail(), false);
  assert.equal(writeLocalDetail(true), false);
});

test('clipboard: API first, textarea fallback, then a clear "unsupported"', async () => {
  const calls = [];
  assert.equal(await copyToClipboard('abc', { navigator: { clipboard: { writeText: async (t) => calls.push(t) } }, document: undefined }), 'copied');
  assert.deepEqual(calls, ['abc']);
  let removed = false;
  const doc = {
    body: { appendChild() {}, removeChild() { removed = true; } },
    createElement: () => ({ style: {}, setAttribute() {}, select() {} }),
    execCommand: (c) => c === 'copy',
  };
  assert.equal(await copyToClipboard('abc', { navigator: { clipboard: { writeText: async () => { throw new Error('denied'); } } }, document: doc }), 'copied');
  assert.equal(removed, true, 'the temporary textarea is removed');
  assert.equal(await copyToClipboard('abc', { navigator: undefined, document: doc }), 'copied');
  assert.equal(await copyToClipboard('abc', { navigator: undefined, document: { ...doc, execCommand: () => false } }), 'unsupported');
  assert.equal(await copyToClipboard('abc', { navigator: undefined, document: undefined }), 'unsupported');
  assert.equal(await copyToClipboard('abc', { navigator: {}, document: { ...doc, createElement() { throw new Error('boom'); } } }), 'unsupported');
});

test('config validation: required entities, domains, unknown keys, optional helper', () => {
  const good = { type: 'custom:ecco-fallback-recovery-card', entities: { ...IDS } };
  const cfg = validateConfig(good);
  assert.equal(cfg.title, 'Fallback / Recovery');
  assert.equal(cfg.show_header, true);
  assert.equal(cfg.technical_detail_entity, null);
  assert.deepEqual({ ...cfg.entities }, { ...IDS });
  assert.ok(Object.isFrozen(cfg.entities));
  const withOpt = validateConfig({ ...good, title: 'X', show_header: false, technical_detail_entity: 'input_boolean.example_detail' });
  assert.equal(withOpt.title, 'X');
  assert.equal(withOpt.show_header, false);
  assert.equal(withOpt.technical_detail_entity, 'input_boolean.example_detail');
  // optional entities may be left out
  const minimal = { entities: Object.fromEntries(card.REQUIRED_ENTITY_KEYS.map((k) => [k, IDS[k]])) };
  assert.equal(Object.keys(validateConfig(minimal).entities).length, 10);
  for (const k of card.REQUIRED_ENTITY_KEYS) {
    const e = { ...IDS }; delete e[k];
    assert.throws(() => validateConfig({ entities: e }), new RegExp(`entities\\.${k} is required`), k);
  }
  assert.throws(() => validateConfig(null), /invalid configuration/);
  assert.throws(() => validateConfig([]), /invalid configuration/);
  assert.throws(() => validateConfig({}), /entities/);
  assert.throws(() => validateConfig({ entities: [] }), /entities/);
  assert.throws(() => validateConfig({ entities: { ...IDS, review_buton: 'sensor.x' } }), /not a known entity key/);
  assert.throws(() => validateConfig({ entities: { ...IDS, review_button: 'switch.example_review' } }), /must be a button/);
  assert.throws(() => validateConfig({ entities: { ...IDS, review_button: 'script.example_review' } }), /must be a button/);
  assert.throws(() => validateConfig({ entities: { ...IDS, review: 'button.example_review' } }), /must be a sensor/);
  assert.throws(() => validateConfig({ entities: { ...IDS, ntp_synced: 'sensor.example' } }), /binary_sensor/);
  assert.throws(() => validateConfig({ entities: { ...IDS, review: 'Sensor.Example' } }), /entity id/);
  assert.throws(() => validateConfig({ entities: { ...IDS, review: 'sensor' } }), /entity id/);
  assert.throws(() => validateConfig({ entities: { ...IDS, review: 5 } }), /entity id/);
  assert.throws(() => validateConfig({ ...good, technical_detail_entity: 'switch.example' }), /input_boolean/);
  assert.throws(() => validateConfig({ ...good, technical_detail_entity: 5 }), /input_boolean/);
  assert.throws(() => validateConfig({ ...good, show_header: 'yes' }), /show_header/);
  assert.throws(() => validateConfig({ ...good, title: 5 }), /title/);
});

test('service calls: only the Review button press and the optional helper toggle can be built or allowed', () => {
  const cfg = validateConfig({ entities: { ...IDS }, technical_detail_entity: 'input_boolean.example_detail' });
  assert.deepEqual(buildServiceCall('review', cfg), { domain: 'button', service: 'press', data: { entity_id: IDS.review_button } });
  assert.deepEqual(buildServiceCall('detail_toggle', cfg), { domain: 'input_boolean', service: 'toggle', data: { entity_id: 'input_boolean.example_detail' } });
  // FB-B2: save / invalidate / arm_on / arm_off are real kinds (see the FB-B2 service-call tests); restore is not
  for (const kind of ['restore', 'acknowledge', 'arm', 'script', '', undefined]) assert.throws(() => buildServiceCall(kind, cfg), /unknown service call kind/);
  assert.throws(() => buildServiceCall('detail_toggle', validateConfig({ entities: { ...IDS } })), /no technical_detail_entity/);
  const ok = (c) => isAllowedServiceCall(c, cfg);
  assert.equal(ok(buildServiceCall('review', cfg)), true);
  assert.equal(ok(buildServiceCall('detail_toggle', cfg)), true);
  const evil = [
    { domain: 'button', service: 'press', data: { entity_id: 'button.somewhere_else' } },
    { domain: 'button', service: 'press', data: { entity_id: IDS.review_button, extra: 1 } },
    { domain: 'button', service: 'press', data: {} },
    { domain: 'button', service: 'press' },
    { domain: 'switch', service: 'turn_on', data: { entity_id: IDS.review_button } },
    { domain: 'script', service: 'turn_on', data: { entity_id: 'script.example' } },
    { domain: 'esphome', service: 'example_action', data: { entity_id: IDS.review_button } },
    { domain: 'input_boolean', service: 'turn_on', data: { entity_id: 'input_boolean.example_detail' } },
    { domain: 'input_boolean', service: 'toggle', data: { entity_id: 'input_boolean.other' } },
    { domain: 'homeassistant', service: 'restart', data: {} },
    null, undefined, 'button.press',
  ];
  for (const c of evil) assert.equal(ok(c), false, JSON.stringify(c));
  assert.equal(isAllowedServiceCall(buildServiceCall('detail_toggle', cfg), validateConfig({ entities: { ...IDS } })), false, 'helper toggle needs the helper configured');
});

test('unusable sentences for every unusable class (S5 S-5, S-6a to S-6d, stale)', () => {
  assert.match(unusableSentence('SAVE_UNCONFIRMED'), /last save could not be confirmed/);
  assert.match(unusableSentence('UNREADABLE'), /storage read error/);
  assert.match(unusableSentence('CORRUPT'), /never overwritten from the dashboard/);
  assert.equal(unusableSentence('PROFILE_LOST', 7), 'The saved profile (last known generation 7) is missing from storage. Review and save a new known-good profile.');
  assert.equal(unusableSentence('PROFILE_LOST', null), 'The saved profile is missing from storage. Review and save a new known-good profile.');
  assert.equal(unusableSentence('PROFILE_STALE'), 'Saved profile is out of step with its record - review and save again.');
  assert.match(unusableSentence('CORRUPT_DOMAIN'), /outside the supported range/);
});

test('obligation vector texts: every kind and domain of the contract alphabet is decoded', () => {
  const { KIND_TEXT, DOMAIN_LABEL, OBL_ORDER } = card;
  assert.deepEqual([...OBL_ORDER], ['FP', 'DP', 'R4', 'MT', 'FS', 'BUS']);
  assert.deepEqual(Object.fromEntries(OBL_ORDER.map((d) => [d, DOMAIN_LABEL[d]])), {
    FP: 'Free Power', DP: 'Dump to Grid', R4: 'Register 244 test', MT: 'Manual TOU', FS: 'Failback record', BUS: 'Inverter bus',
  });
  const contract = { CM: 'clear marker', CA: 'no record stored', CN: 'no durable state', AC: 'is running', ST: 'is starting', RR: 'must restore first',
    PC: 'restore verified, durable clear pending', EN: 'is restoring', ON: 'needs your decision', UR: 'recovery state unreadable',
    MC: 'recovery metadata corrupt', DV: 'stored state disagrees with memory', LK: 'inverter write lock stuck', NP: 'not yet checked',
    OK: 'idle', BY: 'busy' };
  for (const [k, text] of Object.entries(contract)) assert.equal(KIND_TEXT[k], text, k);
  assert.ok(KIND_TEXT.BL, 'boot not loaded');
  // the three S5 kinds that the firmware vector does not use stay decodable
  for (const k of ['CR', 'IF', 'CT', 'ML']) assert.ok(KIND_TEXT[k], k);
  // the advanced card prints every kind of a vector with its meaning and class
  const vm = deriveModel({ ...scenarios.idle_saved, review: 'st=IDLE;prior=-;exp=-;warn=-;obl=FP:AC,DP:ON,R4:UR,MT:CN,FS:MC,BUS:BY;latch=FP,R4;sv=-' }, IDS);
  const rows = card.renderAdvanced(vm, { detailOpen: true }).inner;
  for (const t of ['is running', 'needs your decision', 'recovery state unreadable', 'no durable state', 'recovery metadata corrupt', 'busy']) assert.ok(rows.includes(t), t);
  assert.ok(rows.includes('Free Power, Register 244 test (FP,R4)'), 'latched domains are named');
  assert.equal(vm.obl.length, 6);
});

test('date and time formatters fall back instead of throwing on a bad locale or time zone', () => {
  const ok = card.makeFormatters({ locale: 'en-GB', timeZone: 'UTC' });
  assert.match(ok.dateTime(1789222500), /12 Sep/);
  assert.match(ok.dateTime(1789222500), /14:15/);
  assert.equal(ok.time(Date.UTC(2026, 8, 12, 7, 5, 9)), '07:05:09');
  const bad = card.makeFormatters({ locale: 'not a locale!!', timeZone: 'Mars/Olympus' });
  assert.match(bad.dateTime(1789222500), /2026-09-12 14:15/);
  assert.equal(bad.time(Date.UTC(2026, 8, 12, 7, 5, 9)), '07:05:09');
  assert.doesNotThrow(() => card.makeFormatters().dateTime(0));
});

// ---------------------------------------------------------------------------
// review round pins (RD0-RD10): every one of these was a way for the card to show something the data did not say
// ---------------------------------------------------------------------------
const CLEAR_OBL = 'FP:CM,DP:CM,R4:CM,MT:CN,FS:CA,BUS:OK';
const withReview = (base, from, to) => ({ ...base, review: base.review.replace(from, to) });
const tvFor = (vm) => timeView(card.makeAnchor({ exp: vm.exp, lastChangedMs: T0, nowMs: T0 }), T0);
const NO_TV = timeView(null, T0);
const FMT = { time: () => 'x', dateTime: () => 'x' };

test('RD0: check 4 is judged only where the vector is the review gate\'s current outcome; idle, expired and cleared are "not live"', () => {
  const c4 = (n, s = 0) => {
    const { vm, tv } = build(n, { elapsedS: s });
    return buildChecks(vm, tv)[3];
  };
  // the firmware keeps publishing the last vector after expiry and after a clearing event: never a pass
  const exp = c4('expired');
  assert.equal(exp.state, 'unknown');
  assert.equal(exp.detail, 'Last checked at Review (not live)');
  assert.match(exp.tip, /^At the last review: Free Power CA; Dump to Grid CM;/);
  const clr = c4('cleared');
  assert.equal(clr.state, 'warn', 'a clearing event is a warning, with the B9 detail');
  assert.equal(clr.detail, 'a temporary operation started (Dump to Grid)');
  const ie11 = deriveModel({ ...scenarios.cleared, last_result: 'REVIEW CLEARED - another ECCO write started since Review' }, IDS);
  const ie11c = buildChecks(ie11, NO_TV)[3];
  assert.deepEqual([ie11c.state, ie11c.detail], ['warn', 'another ECCO write started since Review']);
  // an idle state that still carries an all-clear vector
  const idleVec = deriveModel({ ...scenarios.idle_saved, review: `st=IDLE;prior=-;exp=-;warn=-;obl=${CLEAR_OBL};latch=-;sv=-` }, IDS);
  const idle4 = buildChecks(idleVec, NO_TV)[3];
  assert.deepEqual([idle4.state, idle4.detail], ['unknown', 'Last checked at Review (not live)']);
  // a read that did not complete is not live either
  for (const n of ['mismatch', 'read_error', 'bus_busy', 'internal']) {
    assert.equal(c4(n).state, 'unknown', n);
    assert.match(c4(n).detail, /^(Last checked at Review \(not live\)|Checked at Review)$/, n);
  }
  // never reviewed: nothing to qualify
  assert.deepEqual([c4('idle_saved').state, c4('idle_saved').detail], ['unknown', 'Checked at Review']);
  // while a candidate exists (or is being read) a clear vector is a pass, labelled with where it was measured
  for (const n of ['ready_match', 'ready_diff', 'not_saveable', 'reading']) {
    assert.equal(c4(n).state, 'pass', n);
    assert.match(c4(n).detail, /clear at Review$/, n);
  }
  // refusals keep their adverse verdict (that is what the refusal was about)
  assert.equal(c4('refused').state, 'fail');
  // property over every fixture: a pass can only come from a candidate, a read in progress or a refusal
  for (const n of Object.keys(scenarios)) {
    const { vm, tv } = build(n);
    if (buildChecks(vm, tv)[3].state === 'pass') assert.ok(vm.hasCand || vm.review === 'reading' || vm.review === 'refused', n);
  }
});

test('RD0: the card-5 rows for the expired and cleared states say "not live" and never show a green check 4', () => {
  for (const n of ['expired', 'cleared']) {
    const { vm, tv } = build(n);
    const c5 = card.renderChecks(vm, {}, FMT, tv).inner;
    const rows = [...c5.matchAll(/<div class="check (\w+)">/g)].map((m) => m[1]);
    assert.notEqual(rows[3], 'pass', n);
    assert.match(c5, /Review first\. Checks 1–4 are evaluated at Review; 5–6 are live\./);
  }
  const e = build('expired');
  const c = build('cleared');
  assert.match(card.renderChecks(e.vm, {}, FMT, e.tv).inner, /Last checked at Review \(not live\)/);
  assert.match(card.renderChecks(c.vm, {}, FMT, c.tv).inner, /a temporary operation started \(Dump to Grid\)/);
});

test('RD1: eligible needs READY, sv=OK, a save-permitting prior class and a 16-hex review id; check 2 and the footer follow', () => {
  const base = scenarios.ready_diff;
  const vmOf = (patch, from, to) => deriveModel({ ...(from ? withReview(base, from, to) : base), ...patch }, IDS);
  assert.equal(vmOf({}).eligible, true, 'the firmware shape: READY, sv=OK, prior VALID, a real ID');
  const cases = {
    'sv=NO': vmOf({}, 'sv=OK', 'sv=NO:244X'),
    'sv unconfirmed (-)': vmOf({}, 'sv=OK', 'sv=-'),
    'prior UNREADABLE': vmOf({}, 'prior=VALID', 'prior=UNREADABLE'),
    'prior SAVE_UNCONFIRMED': vmOf({}, 'prior=VALID', 'prior=SAVE_UNCONFIRMED'),
    'review id dash': vmOf({ review_id: '-' }),
    'review id short': vmOf({ review_id: '9C21B04E7D185F3' }),
    'review id lower case': vmOf({ review_id: '9c21b04e7d185f3a' }),
    'review id unavailable': vmOf({ review_id: 'unavailable' }),
    'prior not recognised': vmOf({}, 'prior=VALID', 'prior=NEW_CLASS'),
    'prior dash': vmOf({}, 'prior=VALID', 'prior=-'),
    'not saveable state': vmOf({}, 'st=CANDIDATE_READY', 'st=CANDIDATE_NOT_SAVEABLE'),
  };
  for (const [name, vm] of Object.entries(cases)) {
    assert.equal(vm.eligible, false, name);
    const tv = tvFor(vm);
    const checks = buildChecks(vm, tv);
    const foot = card.renderChecks(vm, {}, FMT, tv).inner;
    assert.doesNotMatch(foot, /Save would be allowed/, `${name}: never "allowed"`);
    assert.match(foot, /Save would be refused/, name);
    assert.ok(vm.blockers.length >= 1, `${name}: the candidate card lists a reason`);
    assert.doesNotMatch(card.renderCandidate(vm, {}, FMT, tv).inner, /Candidate ready for save|style="color:var\(--ok\)">Yes/, name);
    if (vm.sv.kind !== 'ok') assert.equal(checks[1].state, 'fail', `${name}: check 2 fails whenever sv is not OK, even for READY`);
  }
  // prior CORRUPT / PROFILE_LOST / ... stay eligible (REPLACE CORRUPT is a FB-B2 confirmation, not a blocker)
  for (const prior of ['NOT_CAPTURED', 'VALID', 'INVALIDATED', 'CORRUPT', 'CORRUPT_DOMAIN', 'PROFILE_LOST', 'PROFILE_STALE']) {
    assert.equal(vmOf({}, 'prior=VALID', `prior=${prior}`).eligible, true, prior);
  }
  // sv texts are the sv-code texts, also for a READY candidate
  const no = cases['sv=NO'];
  assert.equal(no.review, 'ready');
  assert.deepEqual(no.svBlockers, ['Export mode is Zero Export: Fallback V1 can only save a Zero Export profile (244 = 2).']);
  assert.equal(buildChecks(no, tvFor(no))[1].detail, no.svBlockers[0]);
  const unconfirmed = cases['sv unconfirmed (-)'];
  assert.equal(buildChecks(unconfirmed, tvFor(unconfirmed))[1].detail, card.SV_UNCONFIRMED_BLOCKER);
  // the live-match surface does not depend on eligibility
  assert.equal(liveMatch(no, tvFor(no)).word, 'DIFFERS');
});

test('RD2: the obligation vector must be exactly FP,DP,R4,MT,FS,BUS in order, otherwise check 4 is unknown', () => {
  assert.equal(parseObl(CLEAR_OBL).length, 6);
  const bad = [
    'FP:CM', 'FP:CM,DP:CM', Array(6).fill('FP:CM').join(','), 'XX:CM,YY:CM,ZZ:CM,AA:CM,BB:CM,CC:CM',
    'DP:CM,FP:CM,R4:CM,MT:CN,FS:CA,BUS:OK', `${CLEAR_OBL},FP:CM`, 'FP:CM,DP:CM,R4:CM,MT:CN,FS:CA', 'FP:CM,DP:CM,R4:CM,MT:CN,FS:CA,BUS',
    'fp:cm,dp:cm,r4:cm,mt:cn,fs:ca,bus:ok', `${CLEAR_OBL},`, `,${CLEAR_OBL}`, 'FP:CMX,DP:CM,R4:CM,MT:CN,FS:CA,BUS:OK',
  ];
  for (const o of bad) {
    assert.equal(parseObl(o), null, o);
    const vm = deriveModel(withReview(scenarios.ready_match, /obl=[^;]*/, `obl=${o}`), IDS);
    assert.equal(vm.review, 'ready', o);
    assert.equal(vm.oblState, 'invalid', o);
    const c4 = buildChecks(vm, tvFor(vm))[3];
    assert.equal(c4.state, 'unknown', `${o}: never a pass`);
    assert.match(c4.detail, /not recognised/);
  }
  assert.equal(deriveModel(scenarios.idle_saved, IDS).oblState, 'none', 'obl=- is "never evaluated", not "invalid"');
  assert.equal(deriveModel(scenarios.ready_diff, IDS).oblState, 'ok');
  // an unknown kind inside a well-formed vector still fails closed (a lockout), it is not "unknown"
  const lock = deriveModel(withReview(scenarios.ready_match, 'FP:CA', 'FP:ZZ'), IDS);
  assert.equal(buildChecks(lock, tvFor(lock))[3].state, 'fail');
});

test('RD7: text tables are indexed by own property only: constructor / toString / __proto__ never print native code', () => {
  const { own, WARNING_TEXT, LD_TEXT, DF_TEXT, W_TEXT, KIND_TEXT, DOMAIN_LABEL } = card;
  for (const key of ['constructor', 'toString', '__proto__', 'hasOwnProperty', 'valueOf', 'isPrototypeOf']) {
    for (const t of [WARNING_TEXT, LD_TEXT, DF_TEXT, W_TEXT, KIND_TEXT, DOMAIN_LABEL]) assert.equal(own(t, key), undefined, key);
  }
  assert.equal(own(WARNING_TEXT, 'W1'), WARNING_TEXT.W1);
  // the numeric decoders use the same own-property rule
  for (const key of ['constructor', 'toString', '__proto__', 'hasOwnProperty']) {
    assert.equal(dec244(key), `unrecognised (${key})`, key);
    assert.equal(dec243(key), `unrecognised (${key})`, key);
  }
  assert.equal(dec244(2), 'Zero Export');
  assert.equal(dec243(1), 'Load First');
  assert.equal(own(WARNING_TEXT, undefined), undefined);
  assert.equal(own(WARNING_TEXT, 5), undefined);
  const hostile = { ...scenarios.unusable, summary: 'g=-;id=-;at=-;ld=constructor;df=__proto__;w=toString;hw=7;op=-;why=-;werr=-;us=-' };
  const c1 = card.renderProfile(deriveModel(hostile, IDS), { moreInfoEnabled: true }, FMT).inner;
  assert.match(c1, /defect: __proto__/);
  assert.match(c1, /witness: toString/);
  assert.match(c1, /<div>constructor<\/div>/);
  assert.doesNotMatch(c1, /native code|\[object|function /);
  const warned = { ...scenarios.ready_warn, review: scenarios.ready_warn.review.replace(/warn=[^;]*/, 'warn=constructor,toString,__proto__') };
  const vm = deriveModel(warned, IDS);
  assert.deepEqual(vm.warnings.map((w) => w.text), [
    'Warning constructor is not recognised by this card.', 'Warning toString is not recognised by this card.', 'Warning __proto__ is not recognised by this card.',
  ]);
  assert.doesNotMatch(card.renderCandidate(vm, {}, FMT, tvFor(vm)).inner, /native code|\[object/);
  // a witness word that is only a prototype key on a VALID profile prints nothing from the prototype either
  const lag = deriveModel({ ...scenarios.witness_lag, summary: scenarios.witness_lag.summary.replace(/w=\w+/, 'w=constructor') }, IDS);
  assert.doesNotMatch(card.renderProfile(lag, { moreInfoEnabled: false }, FMT).inner, /native code|\[object/);
});

test('RD8 / (c): Live Match counts every differing register (dc and dx together) and keeps the DIFFERS (CONTEXT) headline', () => {
  const { vm, tv } = build('ready_both_diff');
  assert.equal(vm.sl.dx, '10004');
  assert.equal(vm.cx.dc, '008');
  const lm = liveMatch(vm, tv);
  assert.equal(lm.word, 'DIFFERS (CONTEXT)');
  assert.equal(lm.sentence[0], 'Slot times or context differ from the saved profile in 3 places (as of the review ');
  assert.deepEqual(lm.names, ['Slot 2 power', 'Slot 4 source / mode', 'Slot 1 start']);
  assert.equal(lm.names.length, popcount(vm.cx.dc, DC_BITS) + popcount(vm.sl.dx, DX_BITS), 'the sentence counts exactly the registers the chips name');
  // dc alone: one place (unchanged); dx alone: unchanged wording
  assert.match(liveMatch(build('ready_ctx_diff').vm, build('ready_ctx_diff').tv).sentence[0], /in 1 place \(/);
  assert.match(liveMatch(build('ready_diff').vm, build('ready_diff').tv).sentence[0], /^Live settings differ from the saved profile in 2 places/);
  // the count follows the masks for any combination
  for (const [dx, dc, n] of [['00004', '001', 2], ['7FFFF', '1FF', 28], ['00001', '100', 2], ['00000', '1FF', 9]]) {
    const E = { ...scenarios.ready_diff, review_slots: scenarios.ready_diff.review_slots.replace('dx=10004', `dx=${dx}`), review_context: scenarios.ready_diff.review_context.replace('dc=000', `dc=${dc}`) };
    const b = build('ready_diff', { E });
    assert.match(liveMatch(b.vm, b.tv).sentence[0], new RegExp(`in ${n} places? \\(`), `${dx}/${dc}`);
  }
});

test('(b): B3 IDLE with a stale "CANDIDATE READY" B9 is no candidate: no ID, no countdown, no eligibility, no values', () => {
  for (const b9 of [scenarios.ready_diff.last_result, 'CANDIDATE NOT SAVEABLE - slot 2 power 300 W < 500 W (V1 minimum)']) {
    const E = { ...scenarios.idle_saved, last_result: b9 };
    const { vm, anchor, tv } = build('idle_saved', { E });
    assert.equal(vm.review, 'available');
    assert.equal(vm.hasCand, false);
    assert.equal(vm.eligible, false);
    assert.equal(anchor, null, 'no countdown is started from a B9 text');
    assert.equal(tv.has, false);
    assert.equal(liveMatch(vm, tv).word, 'UNKNOWN');
    assert.deepEqual(buildChecks(vm, tv).map((c) => c.state), ['unknown', 'unknown', 'unknown', 'unknown', 'pass', 'pass']);
    const c4 = card.renderCandidate(vm, {}, FMT, tv).inner;
    assert.match(c4, /NO CANDIDATE/);
    assert.doesNotMatch(c4, /Eligible|Candidate ID|Save Fallback Profile|data-t=/);
    assert.equal(buildRegisterTable(vm).mode, 'none');
    assert.equal(reviewButtonState(vm).disabled, false, 'and the operator can simply review again');
  }
});

test('(d): unavailable supervision / NTP is never a pass and never green: unknown rows, grey badges', () => {
  for (const v of ['unavailable', 'unknown', undefined, '', 'maybe']) {
    const E = { ...scenarios.ready_match, supervision_stable: v, supervision_state: v, ntp_synced: v, write_lock: v };
    if (v === undefined) for (const k of ['supervision_stable', 'supervision_state', 'ntp_synced', 'write_lock']) delete E[k];
    const { vm, tv } = build('ready_match', { E });
    const checks = buildChecks(vm, tv);
    // FB-B2 (CARD-01), before: all five values gave ['unknown', 'unknown'] / 'Entity unavailable'. A supervision STATE that is available and is
    // not SUPERVISED ('maybe') now fails check 5 whatever the stable entity says; "unknown" stays for what the card cannot judge at all
    const stateShown = v === 'maybe';
    assert.deepEqual([checks[4].state, checks[5].state], [stateShown ? 'fail' : 'unknown', 'unknown'], String(v));
    assert.deepEqual([checks[4].detail, checks[5].detail], [stateShown ? 'Supervision state is maybe, not SUPERVISED' : 'Entity unavailable', 'Entity unavailable'], String(v));
    const header = card.renderHeader(vm, { showHeader: true, title: 't' });
    assert.equal((header.match(/background:var\(--idle\)/g) || []).length, 3, `${v}: all three badge dots are grey`);
    assert.equal((header.match(/ unavailable</g) || []).length, 3, String(v));
    assert.doesNotMatch(header, /var\(--ok\)|var\(--warn\)/);
    assert.equal(reviewButtonState(vm).disabled, false, 'and it never gates the Review button');
  }
  // a stable supervision on its own does not make the trusted-time row green
  const only = { ...scenarios.ready_match, ntp_synced: 'unavailable' };
  const b = build('ready_match', { E: only });
  assert.deepEqual(buildChecks(b.vm, b.tv).map((c) => c.state), ['pass', 'pass', 'pass', 'pass', 'pass', 'unknown']);
});

test('RD10: one rule for exactly 45 s: more than 45 is plain, 45 and below is "expiring soon" in the countdown AND check 3', () => {
  const E = withReview(scenarios.ready_diff, 'exp=112', 'exp=46');
  const rows = [
    // elapsed s, remaining, bucket, check 3, countdown colour
    [0, 46, 'plenty', 'pass', 'var(--text-2)'],
    [1, 45, 'soon', 'warn', 'var(--warn)'],
    [2, 44, 'soon', 'warn', 'var(--warn)'],
    [31, 15, 'soon', 'warn', 'var(--warn)'],
    [32, 14, 'urgent', 'warn', 'var(--warn)'],
    [45, 1, 'urgent', 'warn', 'var(--warn)'],
    [46, 0, 'zero', 'fail', 'var(--idle)'],
  ];
  for (const [s, rem, bucket, c3, colour] of rows) {
    const { vm, tv } = build('ready_diff', { E, elapsedS: s });
    assert.equal(tv.rem, rem, `rem at +${s}`);
    assert.equal(tv.bucket, bucket, `bucket at ${rem}`);
    assert.equal(buildChecks(vm, tv)[2].state, c3, `check 3 at ${rem}`);
    const kid = card.renderReview(vm, {}, FMT, tv).kids[3];
    assert.equal(/class="count" style="--cc:([^"]*)"/.exec(kid)[1], colour, `countdown colour at ${rem}`);
    assert.equal(/expiring soon/.test(kid), bucket === 'soon' || bucket === 'urgent', `caption at ${rem}`);
  }
  const zero = build('ready_diff', { E, elapsedS: 46 });
  assert.equal(buildChecks(zero.vm, zero.tv)[2].detail, 'Expiring - waiting for the firmware');
});

test('RD10: at zero the card says "expiring", never "expired"; Eligible reads "No (expiring)"', () => {
  const { vm, tv } = build('ready_expiring', { elapsedS: 12 });
  assert.equal(tv.bucket, 'zero');
  const c4 = fillTime(card.renderCandidate(vm, {}, FMT, tv).inner, tv);
  assert.doesNotMatch(c4, /Candidate expired\./);
  assert.equal((c4.match(/Expiring - waiting for the firmware/g) || []).length, 2, 'the row and the footer');
  assert.doesNotMatch(c4, /class="badrow"/, 'no red blocker row');
  assert.match(c4, /class="warnrow"><svg[^>]*><path[^>]*\/><\/svg><span>Expiring - waiting for the firmware<\/span>/);
  // FB-B2: the row label is "Eligible to save" (it no longer names the stage)
  assert.match(c4, /Eligible to save<\/span><span class="v" style="color:var\(--warn\)">No \(expiring\)</);
  assert.match(c4, /<span style="font-weight:700;color:var\(--warn\)">Expiring - waiting for the firmware<\/span>/);
  assert.equal(vm.eligible, true, 'the firmware verdict itself is unchanged (it still publishes READY)');
  // a candidate that was already not eligible keeps its own reasons (and a plain "No")
  const ns = build('not_saveable', { elapsedS: 101 });
  assert.equal(ns.tv.bucket, 'zero');
  const nsHtml = fillTime(card.renderCandidate(ns.vm, {}, FMT, ns.tv).inner, ns.tv);
  assert.match(nsHtml, /Eligible to save<\/span><span class="v" style="color:var\(--bad\)">No</);
  assert.match(nsHtml, /Candidate not saveable/);
  assert.doesNotMatch(nsHtml, /Candidate expired\./);
});

// ---------------------------------------------------------------------------
// final review ACCEPT0: the Live Match sentence never claims more than the firmware published
// ---------------------------------------------------------------------------
const withMasks = (base, { dx, dc, di }) => ({
  ...base,
  review_slots: base.review_slots.replace(/dx=[0-9A-F-]+$/, `dx=${dx}`),
  review_context: base.review_context.replace(/dc=[0-9A-F-]+;di=[0-9A-F-]+$/, `dc=${dc};di=${di}`),
});
const sentenceOf = (E, name = 'ready_match') => {
  const { vm, tv } = build(name, { E });
  const lm = liveMatch(vm, tv);
  return { lm, vm, text: lm.sentence.join('') };
};

test('ACCEPT0: "31 of 31 registers matched" is said only when the information-only mask is zero as well', () => {
  const zero = sentenceOf(scenarios.ready_match);
  assert.equal(zero.lm.word, 'MATCHES SAVED PROFILE');
  assert.deepEqual(zero.lm.sentence, ['31 of 31 registers matched at the review ', 'age', ' ago.'], 'the design sentence, unchanged, when di is zero');

  const info = sentenceOf(scenarios.ready_info_diff, 'ready_info_diff');
  assert.equal(info.lm.word, 'MATCHES SAVED PROFILE', 'the headline stays: E1 and the context are equal');
  assert.equal(info.lm.tone, 'ok');
  assert.deepEqual(info.lm.chips, [], 'information-only registers are not settings: no chips');
  assert.equal(
    info.text,
    'All compared settings and context matched at the review age ago. Info-only values differ (not restored by Fallback V1).',
  );
  assert.doesNotMatch(info.text, /31 of 31/);

  // every non-zero di value (bits 0-4) keeps the headline and never claims 31 of 31; di = 00 always does
  for (let di = 0; di <= 0x1f; di++) {
    const hex = di.toString(16).toUpperCase().padStart(2, '0');
    const { lm, text } = sentenceOf(withMasks(scenarios.ready_match, { dx: '00000', dc: '000', di: hex }));
    assert.equal(lm.word, 'MATCHES SAVED PROFILE', `di=${hex}`);
    if (di === 0) assert.match(text, /^31 of 31 registers matched at the review age ago\.$/, 'di=00');
    else {
      assert.doesNotMatch(text, /31 of 31/, `di=${hex}`);
      assert.match(text, /^All compared settings and context matched at the review age ago\. Info-only values differ \(not restored by Fallback V1\)\.$/, `di=${hex}`);
    }
  }
});

test('ACCEPT0: with no di at all the card claims neither "31 of 31" nor an info-only difference', () => {
  const { lm, text } = sentenceOf(withMasks(scenarios.ready_match, { dx: '00000', dc: '000', di: '-' }));
  assert.equal(lm.word, 'MATCHES SAVED PROFILE');
  assert.equal(text, 'All compared settings and context matched at the review age ago. Info-only values were not compared.');
  assert.doesNotMatch(text, /31 of 31|differ/);
});

test('ACCEPT0: the differing-settings and differing-context sentences never mention "31 of 31" and keep their wording', () => {
  for (const name of ['ready_diff', 'ready_ctx_diff', 'ready_both_diff', 'not_saveable_many', 'ready_warn']) {
    const { lm } = sentenceOf(scenarios[name], name);
    assert.doesNotMatch(lm.sentence.join(''), /31 of 31/, name);
    assert.match(lm.word, /^DIFFERS/, name);
  }
  // across every scenario: "31 of 31" appears only under the MATCHES headline with dx = dc = di = 0
  for (const name of Object.keys(scenarios)) {
    const { vm, tv } = build(name);
    const lm = liveMatch(vm, tv);
    if (!lm.sentence.join('').includes('31 of 31')) continue;
    assert.equal(lm.word, 'MATCHES SAVED PROFILE', name);
    assert.deepEqual([vm.cmp.dx, vm.cmp.dc, vm.cmp.di], ['00000', '000', '00'], name);
  }
});

test('ACCEPT0: the rendered Live Match card never shows "31 of 31" next to a marked info-only difference', () => {
  const r = renderScenario('ready_info_diff');
  const c2 = textNodes(r.out.cards.c2.inner, r.tv).join(' ');
  assert.match(c2, /MATCHES SAVED PROFILE/);
  assert.match(c2, /All compared settings and context matched at the review .* ago\. Info-only values differ \(not restored by Fallback V1\)\./);
  assert.doesNotMatch(c2, /31 of 31/);
  assert.match(r.out.cards.c6.inner, /7000<span class="was">◀ 8000<\/span>/, 'the summary marks the information registers that differ');
  const m = renderScenario('ready_match');
  assert.match(textNodes(m.out.cards.c2.inner, m.tv).join(' '), /31 of 31 registers matched at the review .* ago\./);
});

// ---------------------------------------------------------------------------
// final review FW0: a stored profile the firmware does not trust is never "matched" and never marked
// ---------------------------------------------------------------------------
test('FW0: not_saveable_unreadable (authentic record, effective class UNREADABLE): dx / dc / di are "-", nothing is compared', () => {
  const { vm, tv } = build('not_saveable_unreadable');
  assert.equal(vm.profile, 'unusable');
  assert.equal(vm.b1, 'UNREADABLE');
  assert.equal(vm.prior, 'UNREADABLE');
  assert.equal(vm.savedOK, false, 'B7 / B8 are v=NONE');
  assert.deepEqual([vm.sl.dx, vm.cx.dc, vm.cx.di], ['-', '-', '-'], 'the firmware prints "-" for all three masks');
  assert.deepEqual(vm.cmp, { comparable: false, untrusted: true, dx: '-', dc: '-', di: '-' });
  const lm = liveMatch(vm, tv);
  assert.equal(lm.word, 'UNKNOWN');
  assert.equal(lm.tone, 'idle');
  assert.deepEqual(lm.sentence, [untrustedSentence('UNREADABLE')]);
  assert.equal(lm.sentence[0], 'The stored profile could not be read, so it cannot be trusted and no match is reported.');
  assert.deepEqual(lm.chips, []);
  assert.equal(lm.basis, 'none');
  assert.doesNotMatch(lm.sentence.join(''), /matched|MATCHES|31 of 31|no saved profile/i, 'no match claim, and not "no saved profile" either: the profile exists but is not trusted');
});

test('FW0: the rendered cards say so - no markers, no legend, an explanation, a "not trusted" saved selector, an empty delta column', () => {
  const r = renderScenario('not_saveable_unreadable', { ui: { detailOpen: true } });
  const c2 = textNodes(r.out.cards.c2.inner, r.tv).join(' ');
  assert.match(c2, /UNKNOWN/);
  assert.match(c2, /The stored profile could not be read, so it cannot be trusted and no match is reported\./);
  assert.doesNotMatch(c2, /MATCHES|matched/);
  const c6 = r.out.cards.c6.inner;
  assert.equal((c6.match(/class="diff"/g) || []).length, 0, 'no difference marker');
  assert.doesNotMatch(c6, /legend|◀/);
  assert.match(c6, /Not compared: the stored profile is UNREADABLE and cannot be trusted, so no difference markers are shown\./);
  assert.match(c6, /data-view="saved"[^>]*aria-disabled="true"[^>]*title="The stored profile is UNREADABLE and is not trusted: no saved values are shown\."[^>]*>Saved profile<small>not trusted<\/small>/);
  assert.match(c6, /data-view="cand"[^>]*aria-pressed="true"/, 'the candidate values are still shown');
  const c7 = r.out.cards.c7.inner;
  assert.match(c7, /Not compared: the stored profile is UNREADABLE and cannot be trusted/);
  assert.doesNotMatch(c7, /<span style="color:var\(--(?:text-3|warn)\)">[=≠]<\/span>/, 'no = or ≠ in the delta column');
  const t = buildRegisterTable(r.vm);
  assert.equal(t.rows.length, 31);
  assert.ok(t.rows.every((row) => row.delta === 'none' && row.saved === '—'));
});

test('FW0: robustness - masks published beside an UNREADABLE class (an older or damaged publisher) are still not shown or counted', () => {
  const base = scenarios.not_saveable_unreadable;
  const ui = { detailOpen: true, view: 'auto', pending: false, notice: '', showHeader: true, title: 't', moreInfoEnabled: true };
  for (const [dx, dc, di] of [['00000', '000', '00'], ['10004', '008', '06'], ['7FFFF', '1FF', '1F']]) {
    const E = withMasks(base, { dx, dc, di });
    const { vm, tv } = build('not_saveable_unreadable', { E });
    assert.equal(vm.sl.dx, dx, 'the parsed string is left as published');
    assert.equal(vm.cmp.comparable, false, `${dx}/${dc}/${di}`);
    assert.deepEqual([vm.cmp.dx, vm.cmp.dc, vm.cmp.di], ['-', '-', '-']);
    assert.equal(liveMatch(vm, tv).word, 'UNKNOWN');
    const out = card.renderAll(vm, tv, ui, { time: () => 'x', dateTime: () => 'x' });
    assert.equal((out.cards.c6.inner.match(/class="diff"/g) || []).length, 0, `${dx}: no marker`);
    assert.ok(buildRegisterTable(vm).rows.every((row) => row.delta === 'none'), `${dx}: no delta`);
  }
  // an UNREADABLE class in only one of the two places (B1 or the candidate's prior) is enough
  const priorOnly = { ...scenarios.ready_diff, review: scenarios.ready_diff.review.replace('prior=VALID', 'prior=UNREADABLE') };
  const b1Only = { ...scenarios.ready_diff, profile_state: 'UNREADABLE' };
  for (const [label, E] of [['prior only', priorOnly], ['B1 only', b1Only]]) {
    const { vm, tv } = build('ready_diff', { E });
    assert.equal(vm.cmp.untrusted, true, label);
    assert.equal(vm.cmp.comparable, false, label);
    const lm = liveMatch(vm, tv);
    assert.equal(lm.word, 'UNKNOWN', label);
    assert.deepEqual([lm.names, lm.chips, lm.more], [[], [], 0], `${label}: no chip names a register against an untrusted profile`);
    assert.ok(buildRegisterTable(vm).rows.every((row) => row.delta === 'none'), label);
    assert.match(notComparedNote(vm), /^Not compared: the stored profile is UNREADABLE and cannot be trusted/, label);
  }
});

test('FW0: a trusted stored profile behaves exactly as before: cmp mirrors the published masks', () => {
  for (const name of ['ready_match', 'ready_diff', 'ready_ctx_diff', 'ready_both_diff', 'ready_info_diff', 'not_saveable_many', 'ready_warn', 'transient_op']) {
    const { vm } = build(name);
    assert.deepEqual(vm.cmp, { comparable: true, untrusted: false, dx: vm.sl.dx, dc: vm.cx.dc, di: vm.cx.di }, name);
    assert.equal(notComparedNote(vm), '', name);
  }
  // no candidate: nothing to compare, nothing to explain
  for (const name of ['idle_saved', 'reading', 'expired', 'unavailable']) {
    const { vm } = build(name);
    assert.equal(vm.cmp.comparable, false, name);
    assert.equal(notComparedNote(vm), '', name);
  }
  // no stored profile at all (never captured): no comparison and no extra note (the card already says "no saved profile")
  const nc = build('not_captured_cand').vm;
  assert.equal(nc.cmp.comparable, false);
  assert.equal(nc.cmp.untrusted, false);
  assert.equal(notComparedNote(nc), '');
  assert.deepEqual(savedSegmentNote(nc), { sub: 'no saved profile', tip: 'no saved profile' });
});

test('FW0: a "saved" profile whose candidate carries no masks says the comparison is missing, never "matches"', () => {
  const E = withMasks(scenarios.ready_match, { dx: '-', dc: '-', di: '-' });
  const { vm, tv } = build('ready_match', { E });
  assert.equal(vm.profile, 'saved');
  assert.equal(vm.cmp.comparable, false);
  const lm = liveMatch(vm, tv);
  assert.equal(lm.word, 'UNKNOWN');
  assert.equal(lm.sentence[0], SENTENCE.notComparable);
  assert.equal(lm.basis, 'review');
  assert.match(notComparedNote(vm), /^Not compared: the firmware reported no comparison with the saved profile/);
  // a half-published set (settings but no context mask) is not a comparison either
  const half = withMasks(scenarios.ready_match, { dx: '00000', dc: '-', di: '00' });
  assert.equal(build('ready_match', { E: half }).vm.cmp.comparable, false);
});

test('FW0: Live Match for every stored-profile class says why there is no comparison (idle, no candidate)', () => {
  const lmOf = (b1) => {
    const { vm, tv } = build('idle_saved', { E: { ...scenarios.idle_saved, profile_state: b1 } });
    return liveMatch(vm, tv);
  };
  assert.equal(lmOf('NOT_CAPTURED').sentence[0], SENTENCE.noSavedToCompare);
  assert.equal(lmOf('INVALIDATED').sentence[0], SENTENCE.noSavedToCompare);
  assert.equal(lmOf('UNREADABLE').sentence[0], 'The stored profile could not be read, so it cannot be trusted and no match is reported.');
  assert.equal(lmOf('PROFILE_LOST').sentence[0], 'The saved profile is missing from storage, so there is nothing to compare against.');
  for (const b1 of ['CORRUPT', 'CORRUPT_DOMAIN', 'SAVE_UNCONFIRMED', 'PROFILE_STALE']) {
    assert.equal(lmOf(b1).sentence[0], `The stored profile is ${b1} and cannot be used, so no match is reported.`, b1);
  }
  for (const b1 of card.CLASS_NAMES) {
    if (b1 === 'VALID') continue;
    const lm = lmOf(b1);
    assert.equal(lm.word, 'UNKNOWN', b1);
    assert.doesNotMatch(lm.sentence.join(''), /matched|MATCHES/, b1);
  }
});

test('FW0: the saved-source button names the reason: "not trusted" for an unusable stored profile, "no saved profile" otherwise', () => {
  const note = (b1) => savedSegmentNote(deriveModel({ ...scenarios.idle_saved, profile_state: b1, saved_slots: 'unavailable', saved_context: 'unavailable' }, IDS));
  assert.deepEqual(note('UNREADABLE'), { sub: 'not trusted', tip: 'The stored profile is UNREADABLE and is not trusted: no saved values are shown.' });
  assert.equal(note('CORRUPT').sub, 'not trusted');
  assert.equal(note('PROFILE_LOST').sub, 'no saved profile', 'there is no stored profile to distrust');
  assert.equal(note('NOT_CAPTURED').sub, 'no saved profile');
  assert.equal(note('INVALIDATED').sub, 'no saved profile');
});

// ===========================================================================
// FB-B2: guarded Save / Invalidate. Configuration, service calls, the B9 families, the gates and the request state.
// ===========================================================================
const {
  deriveAct, saveGate, invalidateGate, saveEffect, armButtonState, makeFlow, advanceFlow, flowPendingKind, phraseFor, groupId,
  actResult, FLOW_TEXT, GATE_LABEL, itemBlocks, armView, ARM_TTL_S, ACT_PENDING_TIMEOUT_MS, EXECUTE_SERVICE,
  ARM_OFF_GRACE_MS, expectedGeneration, supervisionStateText,
} = card;

const ARM_KEYS = ['arm', 'free_power_arm', 'dump_arm', 'manual_arm'];
const IDS_NO_ARMS = Object.fromEntries(Object.entries(IDS).filter(([k]) => !ARM_KEYS.includes(k)));
const cfgWith = (extra = {}) => validateConfig({ entities: { ...IDS, ...extra } });
const REVIEW_ID = '9C21B04E7D185F3A';
const PROFILE_ID = '2BAEBFE97F4E04BC';
const mut = (base, patch) => ({ ...scenarios[base], ...patch });
/** A save gate for scenario `name` (arm turned on 3 s after the publish, looked at 10 s after it), with state overrides. */
function gateFor(name, patch = {}, { elapsedS = 10, armOnS = 3, ctx = {}, ids = IDS } = {}) {
  const E = { ...scenarios[name], ...patch };
  const vm = deriveModel(E, ids);
  const anchor = vm.hasCand && vm.exp !== null ? card.makeAnchor({ exp: vm.exp, lastChangedMs: T0, nowMs: T0 }) : null;
  const armAnchor = armOnS === null ? null : card.makeAnchor({ exp: ARM_TTL_S, lastChangedMs: T0 + armOnS * 1000, nowMs: T0 + elapsedS * 1000 });
  const tv = timeView(anchor, T0 + elapsedS * 1000, armAnchor);
  return { vm, tv, gate: saveGate(vm, tv, ctx) };
}
const itemOf = (gate, id) => gate.items.find((i) => i.id === id);
const states = (gate) => Object.fromEntries(gate.items.map((i) => [i.id, i.state]));

test('FB-B2 config: the arm and the three read-only write arms are optional switch entities', () => {
  assert.deepEqual(card.OPTIONAL_ENTITY_KEYS.slice(-4), ARM_KEYS);
  assert.equal(card.ENTITY_KEYS.length, 19);
  const minimal = validateConfig({ entities: Object.fromEntries(card.REQUIRED_ENTITY_KEYS.map((k) => [k, IDS[k]])) });
  for (const k of ARM_KEYS) assert.equal(minimal.entities[k], undefined, `${k} may be left out`);
  const full = cfgWith();
  for (const k of ARM_KEYS) assert.equal(full.entities[k], IDS[k]);
  for (const k of ARM_KEYS) {
    assert.throws(() => cfgWith({ [k]: 'sensor.example' }), /must be a switch/, k);
    assert.throws(() => cfgWith({ [k]: 'button.example' }), /must be a switch/, k);
    assert.throws(() => cfgWith({ [k]: 'Switch.Example' }), /entity id/, k);
    assert.throws(() => cfgWith({ [k]: 5 }), /entity id/, k);
  }
  assert.doesNotThrow(() => validateConfig(card.EccoFallbackRecoveryCard.getStubConfig()), 'the card-picker stub config is valid');
  assert.equal(card.EccoFallbackRecoveryCard.getStubConfig().entities.arm, 'switch.example_arm');
});

test('FB-B2 service calls: arm on / off and the execute action, with the exact phrases', () => {
  const cfg = cfgWith();
  assert.deepEqual(buildServiceCall('arm_on', cfg), { domain: 'switch', service: 'turn_on', data: { entity_id: IDS.arm } });
  assert.deepEqual(buildServiceCall('arm_off', cfg), { domain: 'switch', service: 'turn_off', data: { entity_id: IDS.arm } });
  assert.equal(EXECUTE_SERVICE, 'ecco_clock_dongle_fallback_profile_execute', 'esphome.<node name>_<api action>');
  assert.deepEqual(buildServiceCall('save', cfg, { id: REVIEW_ID }), {
    domain: 'esphome',
    service: EXECUTE_SERVICE,
    data: { action: 'SAVE', target_id: REVIEW_ID, confirmation: 'SAVE 9C21B04E7D185F3A' },
  });
  assert.deepEqual(buildServiceCall('replace_corrupt', cfg, { id: REVIEW_ID }).data, {
    action: 'SAVE', target_id: REVIEW_ID, confirmation: 'SAVE 9C21B04E7D185F3A REPLACE CORRUPT',
  });
  assert.deepEqual(buildServiceCall('invalidate', cfg, { id: PROFILE_ID }).data, {
    action: 'INVALIDATE', target_id: PROFILE_ID, confirmation: 'INVALIDATE 2BAEBFE97F4E04BC',
  });
  assert.equal(phraseFor('SAVE', REVIEW_ID), 'SAVE 9C21B04E7D185F3A');
  assert.equal(phraseFor('SAVE', REVIEW_ID, true), 'SAVE 9C21B04E7D185F3A REPLACE CORRUPT');
  assert.equal(phraseFor('INVALIDATE', PROFILE_ID), 'INVALIDATE 2BAEBFE97F4E04BC');
  // an ID of sixteen digits is still a string: it is never turned into a number (which would lose digits and zeros)
  const digits = '0123456789012345';
  assert.equal(buildServiceCall('save', cfg, { id: digits }).data.target_id, digits);
  assert.equal(typeof buildServiceCall('save', cfg, { id: digits }).data.target_id, 'string');
  // nothing without the arm entity, nothing without a real ID
  const noArm = validateConfig({ entities: { ...IDS_NO_ARMS } });
  for (const kind of ['arm_on', 'arm_off']) assert.throws(() => buildServiceCall(kind, noArm), /no arm entity/, kind);
  for (const kind of ['save', 'replace_corrupt', 'invalidate']) assert.throws(() => buildServiceCall(kind, noArm, { id: REVIEW_ID }), /no arm entity/, kind);
  for (const kind of ['save', 'replace_corrupt', 'invalidate']) {
    for (const id of [undefined, null, 5, 1234567890123456, '', '9c21b04e7d185f3a', '9C21B04E7D185F3', '9C21B04E7D185F3AA', '9C21B04E7D185F3A\n', ' 9C21B04E7D185F3A', '9C21B04E7D185F3G']) {
      assert.throws(() => buildServiceCall(kind, cfg, { id }), /16 hex digit ID/, `${kind} ${JSON.stringify(id)}`);
    }
    assert.throws(() => buildServiceCall(kind, cfg), /16 hex digit ID/);
  }
});

test('FB-B2 allow-list: only the exact arm and execute calls pass; every other shape is refused', () => {
  const cfg = cfgWith();
  const ok = (c, config = cfg) => isAllowedServiceCall(c, config);
  const id = REVIEW_ID;
  for (const kind of ['arm_on', 'arm_off']) assert.equal(ok(buildServiceCall(kind, cfg)), true, kind);
  assert.equal(ok(buildServiceCall('save', cfg, { id })), true);
  assert.equal(ok(buildServiceCall('replace_corrupt', cfg, { id })), true);
  assert.equal(ok(buildServiceCall('invalidate', cfg, { id: PROFILE_ID })), true);
  const exec = (data, over = {}) => ({ domain: 'esphome', service: EXECUTE_SERVICE, data, ...over });
  const good = { action: 'SAVE', target_id: id, confirmation: `SAVE ${id}` };
  assert.equal(ok(exec(good)), true);
  const evil = [
    // the action token: only SAVE and INVALIDATE, upper case, nothing reserved or retired
    ...['RESTORE', 'ACKNOWLEDGE', 'CAPTURE', 'APPLY', 'RETRY_APPLY', 'ACCEPT_LIVE', 'PROVISION', 'save', 'Save', 'SAVE ', ' SAVE', 'INVALIDATE ', '', 'FOO'].map((a) => exec({ ...good, action: a, confirmation: `${a} ${id}` })),
    // the ID: sixteen upper-case hex digits exactly
    ...['9c21b04e7d185f3a', '9C21B04E7D185F3', '9C21B04E7D185F3AA', '9C21B04E7D185F3G', '', 5].map((t) => exec({ ...good, target_id: t, confirmation: `SAVE ${t}` })),
    // the keys: exactly action, target_id, confirmation
    exec({ ...good, extra: 1 }),
    exec({ action: 'SAVE', target_id: id }),
    exec({ action: 'SAVE', confirmation: `SAVE ${id}` }),
    exec({ action: 'SAVE', id, confirmation: `SAVE ${id}` }),
    exec({}),
    exec(null), exec(undefined), exec([]), exec('SAVE'),
    // the phrase: built from the same two values, nothing else
    exec({ ...good, confirmation: 'SAVE 0000000000000000' }),
    exec({ ...good, confirmation: `SAVE ${id}\n` }),
    exec({ ...good, confirmation: `SAVE  ${id}` }),
    exec({ ...good, confirmation: ` SAVE ${id}` }),
    exec({ ...good, confirmation: `save ${id}` }),
    exec({ ...good, confirmation: `SAVE ${id} replace corrupt` }),
    exec({ ...good, confirmation: `SAVE ${id} REPLACE  CORRUPT` }),
    exec({ ...good, confirmation: `SAVE ${id} REPLACE CORRUPT ` }),
    exec({ ...good, confirmation: `INVALIDATE ${id}` }),
    exec({ ...good, confirmation: '' }),
    exec({ ...good, confirmation: 5 }),
    exec({ action: 'INVALIDATE', target_id: id, confirmation: `INVALIDATE ${id} REPLACE CORRUPT` }),
    exec({ action: 'INVALIDATE', target_id: id, confirmation: `SAVE ${id}` }),
    // another service, domain or node
    exec(good, { service: 'ecco_clock_dongle_free_power_recovery_execute' }),
    exec(good, { service: 'other_node_fallback_profile_execute' }),
    exec(good, { service: 'fallback_profile_execute' }),
    exec(good, { domain: 'script' }),
    exec(good, { domain: 'homeassistant' }),
    // the arm: that switch, on or off, with exactly its entity id
    { domain: 'switch', service: 'turn_on', data: { entity_id: 'switch.example_free_power_arm' } },
    { domain: 'switch', service: 'turn_off', data: { entity_id: IDS.dump_arm } },
    { domain: 'switch', service: 'toggle', data: { entity_id: IDS.arm } },
    { domain: 'switch', service: 'turn_on', data: { entity_id: IDS.arm, extra: 1 } },
    { domain: 'switch', service: 'turn_on', data: { entity_id: [IDS.arm] } },
    { domain: 'switch', service: 'turn_on', data: {} },
    { domain: 'switch', service: 'turn_on' },
    { domain: 'homeassistant', service: 'turn_on', data: { entity_id: IDS.arm } },
    { domain: 'script', service: 'turn_on', data: { entity_id: IDS.arm } },
    null, undefined, 'switch.turn_on',
  ];
  for (const c of evil) assert.equal(ok(c), false, JSON.stringify(c));
  // no arm entity configured: no arm call and no execute call
  const noArm = validateConfig({ entities: { ...IDS_NO_ARMS } });
  assert.equal(ok(exec(good), noArm), false);
  assert.equal(ok({ domain: 'switch', service: 'turn_on', data: { entity_id: IDS.arm } }, noArm), false);
  assert.equal(ok(buildServiceCall('review', cfg), noArm), true, 'Review does not need the arm');
});

test('FB-B2 B9 families: generation numbers, the witness flag and the outcome of deriveAct', () => {
  const p = parseB9('SAVED - known-good profile generation 8 saved (verified this boot)');
  assert.deepEqual([p.kind, p.gen, p.newGen, p.witness], ['saved', 8, null, false]);
  const i = parseB9('INVALIDATED - profile generation 7 is no longer usable (now INVALIDATED g8); payload kept for reference; save a new profile to re-enable');
  assert.deepEqual([i.kind, i.gen, i.newGen], ['invalidated', 7, 8]);
  assert.equal(parseB9('SAVE NOT COMMITTED - witness advanced; profile unchanged; stored profile is now out of step - review and save again').witness, true);
  assert.equal(parseB9('SAVE NOT COMMITTED - storage refused the write (E102); nothing changed').witness, false);
  assert.equal(parseB9('INVALIDATE NOT COMMITTED for the profile record, but the generation record advanced: g7 is now STALE (unusable)').witness, true);
  assert.equal(parseB9('SAVE REFUSED - profile generation counter exhausted; profile unchanged').gen, null, 'no digits, no generation');
  // deriveAct: family and outcome for every Save / Invalidate fixture, and `verified` only when B1 and B2 agree with B9
  for (const [name, e] of Object.entries(meta).filter(([, m]) => m.expect.act !== undefined)) {
    const { vm } = build(name);
    assert.equal(vm.act ? `${vm.act.family}:${vm.act.outcome}` : null, e.expect.act, `${name}: act`);
    if ('verified' in e.expect) assert.equal(vm.act.verified, e.expect.verified, `${name}: verified`);
    if ('witness' in e.expect) assert.equal(vm.act.witness, e.expect.witness, `${name}: witness`);
  }
  const base = scenarios.saved_ok;
  const verified = (patch) => deriveModel({ ...base, ...patch }, IDS).act.verified;
  assert.equal(verified({}), true);
  assert.equal(verified({ profile_state: 'INVALIDATED' }), false, 'B1 must say VALID');
  assert.equal(verified({ summary: base.summary.replace('g=8;', 'g=7;') }), false, 'B2 must carry the same generation');
  assert.equal(verified({ summary: base.summary.replace('g=8;', 'g=-;') }), false);
  assert.equal(verified({ last_result: base.last_result.replace('generation 8', 'generation 9') }), false);
  const verifiedInv = (patch) => deriveModel({ ...scenarios.invalidated_ok, ...patch }, IDS).act.verified;
  assert.equal(verifiedInv({}), true);
  assert.equal(verifiedInv({ profile_state: 'VALID' }), false, 'B1 must say INVALIDATED');
  assert.equal(verifiedInv({ summary: scenarios.invalidated_ok.summary.replace('g=8;', 'g=7;') }), false, 'B2 must carry the new generation');
  assert.equal(verifiedInv({ last_result: scenarios.invalidated_ok.last_result.replace('INVALIDATED g8', 'INVALIDATED g9') }), false);
  assert.equal(deriveAct(parseB9('No Fallback Profile action since boot'), 'VALID', 7), null);
  assert.equal(deriveAct(parseB9('REVIEW REFUSED - x'), 'VALID', 7), null);
  assert.equal(deriveAct(parseB9('CANDIDATE READY - x'), 'VALID', 7), null);
  // the tone of each outcome is the existing b9Tone
  for (const [text, tone] of [['SAVED - x generation 1', 'ok'], ['SAVE REFUSED - x', 'warn'], ['SAVE NOT COMMITTED - x', 'bad'], ['SAVE OUTCOME UNKNOWN - x', 'bad'], ['INVALIDATED - x', 'ok'], ['INVALIDATE REFUSED - x', 'warn'], ['INVALIDATE NOT COMMITTED - x', 'bad'], ['INVALIDATE OUTCOME UNKNOWN - x', 'bad'], ['REFUSED - unsupported action', 'warn']]) {
    assert.equal(deriveAct(parseB9(text), 'VALID', 1).tone, tone, text);
  }
});

test('FB-B2 deriveModel: st=SAVING, the arm and the other write arms', () => {
  const s = build('saving').vm;
  assert.deepEqual([s.review, s.st, s.hasCand, s.stKnown], ['saving', 'SAVING', false, true]);
  assert.deepEqual([s.act.family, s.act.outcome], ['save', 'progress']);
  assert.equal(deriveModel({ ...scenarios.saving, last_result: 'No Fallback Profile action since boot' }, IDS).act.outcome, 'progress', 'the state decides, not a stale B9');
  const a = build('arm_on_ready').vm;
  assert.deepEqual(a.arm, { configured: true, state: true });
  assert.deepEqual(build('ready_match').vm.arm, { configured: true, state: false });
  assert.deepEqual(build('arm_unavailable').vm.arm, { configured: true, state: null });
  assert.deepEqual(deriveModel(scenarios.ready_match, IDS_NO_ARMS).arm, { configured: false, state: false }, 'a state without a configured entity is still read, but "configured" says the dashboard has no arm');
  assert.deepEqual(build('ready_other_arm_on').vm.otherArms, { fp: true, dump: false, manual: false, configured: 3 });
  assert.deepEqual(deriveModel(scenarios.ready_match, IDS_NO_ARMS).otherArms, { fp: false, dump: false, manual: false, configured: 0 });
  assert.deepEqual(deriveModel({ ...scenarios.ready_match, dump_arm: 'unavailable' }, IDS).otherArms.dump, null);
  assert.equal(deriveModel(scenarios.ready_match, undefined).arm.configured, false, 'no ids at all: nothing is configured');
});

test('FB-B2 arm countdown: anchored at the switch change, 120 s, "expiring…" at zero and never declared off', () => {
  const at = (s, onS = 0) => armView(card.makeAnchor({ exp: ARM_TTL_S, lastChangedMs: T0 + onS * 1000, nowMs: T0 + s * 1000 }), T0 + s * 1000);
  assert.deepEqual(at(0), { has: true, rem: 120, bucket: 'plenty' });
  assert.equal(at(75).rem, 45);
  assert.equal(at(75).bucket, 'soon');
  assert.equal(at(106).bucket, 'urgent');
  assert.deepEqual([at(120).rem, at(120).bucket], [0, 'zero']);
  assert.deepEqual([at(500).rem, at(500).bucket], [0, 'zero'], 'it stays "expiring" until the dongle turns the switch off');
  assert.deepEqual(armView(null, T0), { has: false, rem: null, bucket: null });
  assert.equal(timeTexts(timeView(null, T0 + 5000, card.makeAnchor({ exp: ARM_TTL_S, lastChangedMs: T0, nowMs: T0 + 5000 }))).arm, '1:55');
  assert.equal(timeTexts(timeView(null, T0 + 130_000, card.makeAnchor({ exp: ARM_TTL_S, lastChangedMs: T0, nowMs: T0 + 130_000 }))).arm, 'expiring…');
  // a change time in the future (browser clock behind the server) is clamped, so the countdown never runs backwards
  assert.equal(at(0, 30).rem, 120);
  // the candidate countdown is unchanged by the arm anchor
  const { tv } = build('ready_diff', { elapsedS: 40, armOnS: 10 });
  assert.equal(tv.rem, 72);
  assert.equal(tv.arm.rem, 90);
});

test('FB-B2 save gate: everything passing allows the save; the effect is first / replace / REPLACE CORRUPT with the expected generation', () => {
  const g = gateFor('arm_on_ready').gate;
  assert.equal(g.allowed, true);
  assert.equal(g.allowedToArm, true);
  assert.equal(g.why, '');
  assert.equal(g.id, '5F3A9C21B04E7D18');
  assert.equal(g.phrase, 'SAVE 5F3A9C21B04E7D18');
  assert.equal(g.variant, 'save');
  assert.deepEqual(g.items.map((i) => i.id), ['arm', 'flow', 'candidate', 'fresh', 'stored', 'heartbeat', 'ntp', 'arms', 'bus', 'obligations']);
  assert.ok(g.items.every((i) => i.state === 'pass'), JSON.stringify(states(g)));
  assert.equal(itemOf(g, 'arm').detail, '@arm@ left');
  assert.equal(itemOf(g, 'fresh').detail, '@rem@ left');
  // the effect: what the save does and the generation it expects (max of the record and the generation record, plus one)
  const eff = (name, patch = {}) => saveEffect(deriveModel({ ...scenarios[name], ...patch }, IDS));
  assert.deepEqual(eff('arm_on_ready'), { kind: 'replace', gen: 8, replaces: { cls: 'VALID', gen: 7 }, sentence: 'Replaces the saved profile (generation 7). Expected result: generation 8.' });
  assert.deepEqual(eff('arm_on_first'), { kind: 'first', gen: 1, replaces: null, sentence: 'First save: no profile is stored yet. Expected result: generation 1.' });
  assert.equal(eff('arm_on_corrupt').kind, 'replace_corrupt');
  assert.equal(eff('arm_on_corrupt').gen, 8, 'the generation record (hw 7) sets the base for a damaged profile');
  assert.match(eff('arm_on_corrupt').sentence, /^Replaces a damaged stored profile\./);
  const lost = eff('arm_on_ready', { review: scenarios.arm_on_ready.review.replace('prior=VALID', 'prior=PROFILE_LOST') });
  assert.equal(lost.kind, 'replace_lost');
  assert.match(lost.sentence, /The stored profile is missing \(last known generation 7\)\. A new one replaces it\. Expected result: generation 8\./);
  for (const [prior, word] of [['INVALIDATED', 'the invalidated profile'], ['CORRUPT_DOMAIN', 'a stored profile whose values are out of range'], ['PROFILE_STALE', 'a stored profile that is out of step']]) {
    const e = eff('arm_on_ready', { review: scenarios.arm_on_ready.review.replace('prior=VALID', `prior=${prior}`) });
    assert.equal(e.kind, 'replace', prior);
    assert.equal(e.sentence, `Replaces ${word} (generation 7). Expected result: generation 8.`, prior);
  }
  assert.equal(saveEffect(deriveModel(scenarios.idle_saved, IDS)).kind, null, 'no candidate, no effect');
  // a witness ahead of the record raises the expected generation
  assert.equal(eff('arm_on_ready', { summary: scenarios.arm_on_ready.summary.replace('hw=7', 'hw=9') }).gen, 10);
});

test('FB-B2 save gate: REPLACE CORRUPT only for a CORRUPT prior, and it changes the phrase', () => {
  const c = gateFor('arm_on_corrupt').gate;
  assert.equal(c.allowed, true);
  assert.equal(c.variant, 'replace_corrupt');
  assert.equal(c.phrase, 'SAVE C0FFEE00C0FFEE01 REPLACE CORRUPT');
  assert.equal(itemOf(c, 'stored').detail, 'Damaged: saving replaces it (REPLACE CORRUPT confirmation)');
  for (const prior of ['NOT_CAPTURED', 'VALID', 'INVALIDATED', 'CORRUPT_DOMAIN', 'PROFILE_LOST', 'PROFILE_STALE']) {
    const g = gateFor('arm_on_ready', { review: scenarios.arm_on_ready.review.replace('prior=VALID', `prior=${prior}`) }).gate;
    assert.equal(g.allowed, true, prior);
    assert.equal(g.variant, 'save', prior);
    assert.equal(g.phrase, 'SAVE 5F3A9C21B04E7D18', `${prior}: no REPLACE CORRUPT`);
  }
  // UNREADABLE and SAVE_UNCONFIRMED never save (a restart re-derives them)
  for (const prior of ['UNREADABLE', 'SAVE_UNCONFIRMED']) {
    const g = gateFor('arm_on_ready', { review: scenarios.arm_on_ready.review.replace('prior=VALID', `prior=${prior}`) }).gate;
    assert.equal(g.allowed, false, prior);
    assert.equal(itemOf(g, 'stored').state, 'fail', prior);
    assert.equal(itemOf(g, 'stored').detail, `Stored profile is ${prior}: saving stays disabled until the dongle restarts.`);
    assert.equal(g.allowedToArm, false);
  }
  const unknown = gateFor('arm_on_ready', { review: scenarios.arm_on_ready.review.replace('prior=VALID', 'prior=NEW_CLASS') }).gate;
  assert.equal(itemOf(unknown, 'stored').state, 'unknown');
  assert.equal(unknown.allowed, false, 'a class this card does not know is never saved over');
});

test('FB-B2 save gate: each prerequisite failing alone stops the save, with the firmware wording', () => {
  const base = scenarios.arm_on_ready;
  const alone = (patch, id, state, detail, opts = {}) => {
    const { gate } = gateFor('arm_on_ready', patch, opts);
    const it = itemOf(gate, id);
    assert.equal(it.state, state, `${id}: ${JSON.stringify(patch)}`);
    if (detail !== undefined) assert.equal(it.detail, detail, id);
    const others = gate.items.filter((i) => i.id !== id);
    assert.ok(others.every((i) => i.state === 'pass'), `only ${id} differs: ${JSON.stringify(states(gate))}`);
    return gate;
  };
  // G2 the arm
  let g = alone({ arm: 'off' }, 'arm', 'fail', 'ECCO Fallback Profile Arm is not on');
  assert.deepEqual([g.allowed, g.allowedToArm], [false, true], 'only the arm is missing: Arm Save is offered');
  assert.equal(g.why, 'ECCO Fallback Profile Arm is not on');
  g = alone({ arm: 'unavailable' }, 'arm', 'unknown', 'The arm entity is unavailable');
  assert.equal(g.allowed, false, 'an arm the card cannot read is never assumed on');
  g = gateFor('arm_on_ready', {}, { ids: IDS_NO_ARMS }).gate;
  assert.equal(itemOf(g, 'arm').state, 'fail');
  assert.equal(itemOf(g, 'arm').detail, 'Saving is not set up on this dashboard: the arm entity is missing from the card configuration.');
  assert.equal(g.allowed, false);
  // the arm's own 120 s: at zero it is "expiring" and no confirm is offered
  g = gateFor('arm_on_ready', { review: base.review.replace('exp=87', 'exp=120') }, { armOnS: 3, elapsedS: 123 }).gate;
  assert.equal(itemOf(g, 'arm').state, 'fail');
  assert.equal(itemOf(g, 'arm').detail, 'The arm is expiring - turn it off and arm again');
  assert.equal(g.allowed, false);
  g = gateFor('arm_on_ready', {}, { ctx: { cancelling: true } }).gate;
  assert.equal(itemOf(g, 'arm').detail, 'The arm is being turned off');
  assert.equal(g.allowed, false);
  // G1 another operation
  g = gateFor('arm_on_ready', {}, { ctx: { pending: true } }).gate;
  assert.equal(itemOf(g, 'flow').detail, 'another Fallback Profile operation is in progress');
  assert.equal(g.allowed, false);
  assert.equal(g.allowedToArm, false);
  // G3 / G4 the candidate
  g = gateFor('arm_on_ready', { review: base.review.replace('st=CANDIDATE_READY', 'st=CANDIDATE_NOT_SAVEABLE') }).gate;
  assert.equal(itemOf(g, 'candidate').detail, 'This candidate is not saveable: see the reasons above');
  g = gateFor('arm_on_ready', { review: base.review.replace('sv=OK', 'sv=NO:244X') }).gate;
  assert.equal(itemOf(g, 'candidate').detail, 'Export mode is Zero Export: Fallback V1 can only save a Zero Export profile (244 = 2).');
  g = gateFor('arm_on_ready', { review_id: '-' }).gate;
  assert.equal(itemOf(g, 'candidate').detail, 'The candidate has no valid ID, so it cannot be saved.');
  g = gateFor('arm_on_ready', { review: 'st=IDLE;prior=-;exp=-;warn=-;obl=-;latch=-;sv=-', review_id: '-' }).gate;
  assert.equal(itemOf(g, 'candidate').detail, 'no saveable candidate - press Review Current Configuration first');
  assert.equal(itemOf(g, 'fresh').state, 'unknown');
  assert.equal(g.allowed, false);
  g = gateFor('arm_on_ready', {}, { elapsedS: 87 }).gate;
  assert.equal(itemOf(g, 'fresh').state, 'fail');
  assert.equal(itemOf(g, 'fresh').detail, 'The candidate is expiring: review again');
  assert.equal(g.allowed, false);
  // G10 heartbeat: SUPERVISED and a stable run of beats, both
  alone({ supervision_stable: 'off', supervision_state: 'SUSPECT' }, 'heartbeat', 'fail', 'Home Assistant heartbeat is not stable; wait until the dashboard shows it healthy, then review and save again');
  alone({ supervision_stable: 'off', supervision_state: 'SUPERVISED' }, 'heartbeat', 'fail', 'Home Assistant heartbeat is not stable; wait until the dashboard shows it healthy, then review and save again');
  alone({ supervision_stable: 'on', supervision_state: 'SUSPECT' }, 'heartbeat', 'fail', 'Supervision state is SUSPECT, not SUPERVISED');
  alone({ supervision_stable: 'on', supervision_state: 'unavailable' }, 'heartbeat', 'unknown', 'not shown on this dashboard; the dongle checks it when you save');
  g = alone({ supervision_stable: 'unavailable' }, 'heartbeat', 'unknown');
  assert.equal(g.allowed, true, 'an item the card cannot judge does not stop a save: the dongle checks it');
  // G11 trusted time
  alone({ ntp_synced: 'off' }, 'ntp', 'fail', 'clock not NTP-synchronised this boot; the capture time would be untrusted');
  assert.equal(alone({ ntp_synced: 'unavailable' }, 'ntp', 'unknown').allowed, true);
  // G12 the three other write arms
  alone({ free_power_arm: 'on' }, 'arms', 'fail', 'a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first (on now: Free Power)');
  alone({ dump_arm: 'on' }, 'arms', 'fail', 'a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first (on now: Dump to Grid)');
  alone({ manual_arm: 'on' }, 'arms', 'fail', 'a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first (on now: Manual configuration)');
  alone({ free_power_arm: 'on', manual_arm: 'on' }, 'arms', 'fail', 'a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first (on now: Free Power, Manual configuration)');
  alone({ dump_arm: 'unavailable' }, 'arms', 'unknown', 'not shown on this dashboard; the dongle checks it when you save');
  // G14 the bus
  alone({ write_lock: 'on' }, 'bus', 'fail', 'another inverter transaction is in progress; try again shortly');
  assert.equal(alone({ write_lock: 'unavailable' }, 'bus', 'unknown').allowed, true);
  // G15 / G16 temporary operations as of the review: any non-clear entry
  alone({ review: base.review.replace('DP:CM', 'DP:AC') }, 'obligations', 'fail', 'Dump to Grid is running');
  alone({ review: base.review.replace('FP:CA', 'FP:ON').replace('R4:CA', 'R4:UR') }, 'obligations', 'fail', 'Free Power needs your decision; Register 244 test recovery state unreadable');
  alone({ review: base.review.replace(/obl=[^;]*/, 'obl=FP:CA,DP:CM') }, 'obligations', 'unknown', 'Obligation vector not recognised');
});

test('FB-B2 armButtonState: Arm Save is enabled only when everything except the arm passes and the arm is off', () => {
  const state = (name, patch = {}, o = {}) => {
    const { vm, gate } = gateFor(name, patch, { armOnS: null, ctx: o.ctx });
    return armButtonState(gate, vm, o.btn);
  };
  assert.deepEqual(state('ready_match'), { disabled: false, why: '' });
  assert.deepEqual(state('arm_on_ready'), { disabled: true, why: 'The arm is already on' });
  assert.deepEqual(state('arm_on_ready', {}, { btn: { cancelling: true } }), { disabled: true, why: 'The arm is being turned off' });
  assert.deepEqual(state('arm_unavailable'), { disabled: true, why: 'The arm entity is unavailable' });
  assert.deepEqual(state('ready_match', {}, { btn: { pending: true } }), { disabled: true, why: 'Arm requested' });
  assert.deepEqual(state('ready_other_arm_on'), { disabled: true, why: 'a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first (on now: Free Power)' });
  assert.deepEqual(state('ready_nosup'), { disabled: true, why: 'Home Assistant heartbeat is not stable; wait until the dashboard shows it healthy, then review and save again' });
  assert.deepEqual(state('ready_bus_busy'), { disabled: true, why: 'another inverter transaction is in progress; try again shortly' });
  assert.deepEqual(state('not_saveable'), { disabled: true, why: 'This candidate is not saveable: see the reasons above' });
  const noArm = gateFor('ready_match', {}, { ids: IDS_NO_ARMS, armOnS: null });
  assert.deepEqual(armButtonState(noArm.gate, noArm.vm), { disabled: true, why: FLOW_TEXT.notSetUp });
  assert.deepEqual(armButtonState(noArm.gate, noArm.vm, { kind: 'invalidate' }), { disabled: true, why: FLOW_TEXT.invalidateNotSetUp });
  // a candidate that is about to expire is not armed
  const late = gateFor('ready_match', {}, { armOnS: null, elapsedS: 87 });
  assert.equal(armButtonState(late.gate, late.vm).disabled, true);
  // itemBlocks: fail always, unknown only when required
  assert.equal(itemBlocks({ state: 'fail', required: false }), true);
  assert.equal(itemBlocks({ state: 'unknown', required: true }), true);
  assert.equal(itemBlocks({ state: 'unknown', required: false }), false);
  assert.equal(itemBlocks({ state: 'pass', required: true }), false);
  assert.ok(Object.keys(GATE_LABEL).length >= 13);
});

test('FB-B2 invalidate gate: only a VALID profile, no operation in flight, a free bus, a binding that agrees, the arm', () => {
  const gateOfInv = (name, patch = {}, o = {}) => {
    const E = { ...scenarios[name], ...patch };
    const vm = deriveModel(E, o.ids || IDS);
    const armAnchor = card.makeAnchor({ exp: ARM_TTL_S, lastChangedMs: T0 + 2000, nowMs: T0 + 10_000 });
    const tv = timeView(null, T0 + 10_000, armAnchor);
    return { vm, gate: invalidateGate(vm, tv, o.ctx || {}) };
  };
  let { gate } = gateOfInv('arm_on_no_candidate');
  assert.equal(gate.allowed, true);
  assert.equal(gate.id, PROFILE_ID);
  assert.equal(gate.phrase, 'INVALIDATE 2BAEBFE97F4E04BC', 'the FULL 16-hex binding, not the 8-hex short ID');
  assert.deepEqual(gate.items.map((i) => i.id), ['arm', 'flow', 'profile', 'generation', 'binding', 'bus']);
  assert.ok(gate.items.every((i) => i.state === 'pass'));
  assert.equal(gate.discardsCandidate, false);
  assert.equal(invalidateGate(build('arm_on_ready').vm, build('arm_on_ready', { armOnS: 1 }).tv, {}).discardsCandidate, true, 'a pending candidate is discarded: the panel says so');
  // class: VALID only (B8 lagging witness included: the profile is still VALID)
  for (const b1 of ['NOT_CAPTURED', 'INVALIDATED', 'CORRUPT', 'CORRUPT_DOMAIN', 'UNREADABLE', 'PROFILE_LOST', 'SAVE_UNCONFIRMED', 'PROFILE_STALE']) {
    ({ gate } = gateOfInv('arm_on_no_candidate', { profile_state: b1 }));
    assert.equal(gate.allowed, false, b1);
    assert.equal(itemOf(gate, 'profile').detail, `profile is ${b1}; only a VALID profile can be invalidated`, b1);
  }
  ({ gate } = gateOfInv('arm_on_no_candidate', { summary: scenarios.witness_lag.summary }));
  assert.equal(gate.allowed, true, 'VALID with a lagging witness can be invalidated');
  ({ gate } = gateOfInv('arm_on_no_candidate', { summary: scenarios.idle_saved.summary.replace(/id=[0-9A-F]{16}/, 'id=-') }));
  assert.equal(gate.allowed, false);
  assert.equal(itemOf(gate, 'profile').detail, 'The saved profile ID is not available yet');
  // generation: below 4294967295
  ({ gate } = gateOfInv('arm_on_no_candidate', { summary: scenarios.idle_saved.summary.replace('g=7;', 'g=4294967295;'), saved_slots: scenarios.idle_saved.saved_slots.replace('g=7;', 'g=4294967295;') }));
  assert.equal(itemOf(gate, 'generation').detail, 'generation counter exhausted');
  assert.equal(gate.allowed, false);
  ({ gate } = gateOfInv('arm_on_no_candidate', { summary: scenarios.idle_saved.summary.replace('g=7;', 'g=4294967294;') }));
  assert.equal(itemOf(gate, 'generation').state, 'pass');
  // binding: B7's b= must be the first 8 digits of the B2 id
  ({ gate } = gateOfInv('arm_on_no_candidate', { saved_slots: scenarios.idle_saved.saved_slots.replace('b=2BAEBFE9', 'b=00000000') }));
  assert.equal(itemOf(gate, 'binding').state, 'fail');
  assert.equal(gate.allowed, false);
  ({ gate } = gateOfInv('arm_on_no_candidate', { saved_slots: 'v=NONE;g=-;244=-;1=-;2=-;3=-;4=-;5=-;6=-;dx=-;b=-', saved_context: scenarios.not_captured.saved_context }));
  assert.equal(itemOf(gate, 'binding').state, 'fail', 'no saved view to cross-check: not allowed');
  // an operation in flight, the bus, the arm
  ({ gate } = gateOfInv('arm_on_no_candidate', {}, { ctx: { pending: true } }));
  assert.equal(itemOf(gate, 'flow').detail, 'another Fallback Profile operation is in progress');
  for (const review of ['reading', 'saving']) {
    ({ gate } = gateOfInv('arm_on_no_candidate', { review: scenarios[review].review }));
    assert.equal(itemOf(gate, 'flow').state, 'fail', review);
  }
  ({ gate } = gateOfInv('arm_on_no_candidate', { write_lock: 'on' }));
  assert.equal(itemOf(gate, 'bus').detail, 'another inverter transaction is in progress; try again shortly');
  assert.equal(gate.allowed, false);
  ({ gate } = gateOfInv('arm_on_no_candidate', { arm: 'off' }));
  assert.deepEqual([gate.allowed, gate.allowedToArm], [false, true]);
  ({ gate } = gateOfInv('arm_on_no_candidate', {}, { ids: IDS_NO_ARMS }));
  assert.equal(itemOf(gate, 'arm').detail, FLOW_TEXT.invalidateNotSetUp);
  // NOT required: supervision, trusted time, the other write arms, clear obligations (it is the safe direction)
  ({ gate } = gateOfInv('arm_on_no_candidate', { supervision_stable: 'off', supervision_state: 'LOST', ntp_synced: 'off', free_power_arm: 'on', dump_arm: 'on', manual_arm: 'on' }));
  assert.equal(gate.allowed, true);
  assert.equal(gate.items.some((i) => ['heartbeat', 'ntp', 'arms', 'obligations'].includes(i.id)), false);
});

test('FB-B2 request state: sent, running, answered, timed out; a periodic re-publish is not an answer; nothing retries', () => {
  const keys = { review: 'r', b9: 'b', arm: 'a' };
  const vm = build('arm_on_ready').vm;
  const f0 = makeFlow('save', { id: REVIEW_ID, variant: 'save', effect: saveEffect(vm), vm, nowMs: T0, keys });
  assert.deepEqual(f0, { kind: 'save', state: 'sent', id: REVIEW_ID, variant: 'save', gen: 8, effectKind: 'replace', replaces: { cls: 'VALID', gen: 7 }, atMs: T0, review0: 'ready', b9Key: 'b', armOn: true });
  assert.equal(flowPendingKind(f0), 'save');
  assert.equal(flowPendingKind(null), null);
  assert.equal(flowPendingKind({ ...f0, state: 'timeout' }), null);
  assert.equal(flowPendingKind({ ...f0, state: 'unsure' }), null);
  assert.equal(flowPendingKind({ ...f0, state: 'running' }), 'save');
  const snap = (over = {}) => ({ review: 'ready', b9Key: 'b', armState: true, nowMs: T0 + 1000, ...over });
  // nothing changed: still waiting (the exp tick re-publishes B3 about every 10 s; that never answers the request)
  assert.equal(advanceFlow(f0, snap()), f0);
  assert.equal(advanceFlow(f0, snap({ nowMs: T0 + 29_000 })), f0);
  // the dongle reports SAVING: running, until it is no longer SAVING
  const running = advanceFlow(f0, snap({ review: 'saving' }));
  assert.equal(running.state, 'running');
  assert.equal(advanceFlow(running, snap({ review: 'saving', b9Key: 'b2' })), running);
  assert.equal(flowPendingKind(running), 'save');
  assert.equal(advanceFlow(running, snap({ review: 'available', b9Key: 'b3', armState: false })), null, 'the outcome is B9 from here on');
  // answered without ever showing SAVING: the review state, the B9 text or the arm changed
  assert.equal(advanceFlow(f0, snap({ review: 'available' })), null);
  assert.equal(advanceFlow(f0, snap({ b9Key: 'other' })), null);
  // FB-B2 (CARD-05), before: `advanceFlow(f0, snap({ armState: false })) === null` ("every execute call turns the arm off"). The dongle publishes the arm
  // turning off BEFORE B3 / B9 and Home Assistant may deliver them as separate updates, so the arm-off echo alone is NOT an answer; it is one only
  // once the arm has stayed off for ARM_OFF_GRACE_MS with B3 and B9 unchanged
  assert.equal(advanceFlow(f0, snap({ armState: false })), f0, 'the arm-off echo alone keeps the request pending');
  assert.equal(advanceFlow(f0, snap({ armState: false, nowMs: T0 + ARM_OFF_GRACE_MS - 1 })), f0);
  assert.equal(advanceFlow(f0, snap({ armState: false, nowMs: T0 + ARM_OFF_GRACE_MS })), null, 'an arm that stays off past the grace ends it');
  assert.equal(advanceFlow(f0, snap({ armState: null })), f0, 'an unavailable arm is not an answer');
  // no answer: after 30 s it becomes a message; it never goes back to sent and never resends
  const late = advanceFlow(f0, snap({ nowMs: T0 + ACT_PENDING_TIMEOUT_MS }));
  assert.equal(late.state, 'timeout');
  assert.equal(advanceFlow(f0, snap({ nowMs: T0 + ACT_PENDING_TIMEOUT_MS - 1 })), f0);
  assert.equal(advanceFlow(late, snap({ nowMs: T0 + 10 * ACT_PENDING_TIMEOUT_MS })), late, 'a timeout stays until the dongle answers');
  assert.equal(advanceFlow(late, snap({ b9Key: 'x' })), null);
  const unsure = { ...f0, state: 'unsure' };
  assert.equal(advanceFlow(unsure, snap({ nowMs: T0 + 10 * ACT_PENDING_TIMEOUT_MS })), unsure);
  assert.equal(advanceFlow(null, snap()), null);
  // an invalidate request has no SAVING state: only the answer ends it
  const inv = makeFlow('invalidate', { id: PROFILE_ID, vm: build('arm_on_no_candidate').vm, nowMs: T0, keys });
  assert.deepEqual([inv.kind, inv.review0, inv.gen, inv.variant], ['invalidate', 'available', null, 'save']);
  assert.equal(advanceFlow(inv, { review: 'available', b9Key: 'b', armState: true, nowMs: T0 + 1000 }), inv, 'nothing changed: still waiting');
  assert.equal(advanceFlow(inv, { review: 'available', b9Key: 'b2', armState: true, nowMs: T0 + 1000 }), null, 'the last-action text changed');
  // FB-B2 (CARD-05), before: the arm turning off ended an invalidate request at once; now only after the grace (or with B3 / B9)
  assert.equal(advanceFlow(inv, { review: 'available', b9Key: 'b', armState: false, nowMs: T0 + 1000 }), inv, 'the arm turned off: not an answer by itself');
  assert.equal(advanceFlow(inv, { review: 'available', b9Key: 'b', armState: false, nowMs: T0 + ARM_OFF_GRACE_MS }), null, 'the arm stayed off past the grace');
  assert.equal(advanceFlow(inv, { review: 'saving', b9Key: 'b', armState: true, nowMs: T0 + 1000 }), null, 'a changed review state ends it; SAVING never turns an invalidate request into a "running" save');
  assert.equal(advanceFlow({ ...inv, review0: 'saving' }, { review: 'saving', b9Key: 'b', armState: true, nowMs: T0 + 1000 }).state, 'sent');
});

test('FB-B2 Review button and Live Match while a save is running or a request is on its way', () => {
  assert.deepEqual(reviewButtonState(build('saving').vm), { disabled: true, why: 'Save in progress' });
  assert.deepEqual(reviewButtonState(build('idle_saved').vm, { act: 'save' }), { disabled: true, why: 'Save in progress' });
  assert.deepEqual(reviewButtonState(build('idle_saved').vm, { act: 'invalidate' }), { disabled: true, why: 'Invalidate in progress' });
  assert.deepEqual(reviewButtonState(build('idle_saved').vm, { act: null }), { disabled: false, why: '' });
  assert.deepEqual(reviewButtonState(build('reading').vm, { act: 'save' }), { disabled: true, why: 'Review in progress' }, 'the first reason wins');
  const lm = liveMatch(build('saving').vm, build('saving').tv);
  assert.equal(lm.word, 'CHECKING');
  assert.equal(lm.tone, 'busy');
  assert.equal(lm.sentence[0], 'Re-reading the inverter before saving.');
  assert.equal(liveMatch(build('reading').vm, build('reading').tv).sentence[0], 'Reading the inverter now.');
  // checks: while saving the first one is in progress, the rest are not judged
  const checks = buildChecks(build('saving').vm, build('saving').tv);
  assert.deepEqual([checks[0].state, checks[0].detail], ['pending', 'Re-reading before the commit']);
});

test('FB-B2 check 5 needs the state SUPERVISED and a stable run of beats, both ("SUPERVISED alone is insufficient")', () => {
  const c5 = (patch) => {
    const { vm, tv } = build('ready_match', { E: { ...scenarios.ready_match, ...patch } });
    const c = buildChecks(vm, tv)[4];
    return [c.state, c.detail];
  };
  assert.deepEqual(c5({}), ['pass', 'Home Assistant heartbeat stable']);
  assert.deepEqual(c5({ supervision_stable: 'on', supervision_state: 'SUSPECT' }), ['fail', 'Supervision state is SUSPECT, not SUPERVISED']);
  assert.deepEqual(c5({ supervision_stable: 'on', supervision_state: 'unavailable' }), ['unknown', 'Stable, but the supervision state is not shown']);
  assert.deepEqual(c5({ supervision_stable: 'off', supervision_state: 'SUPERVISED' }), ['warn', 'Recovering - waiting for a stable run of beats']);
  assert.deepEqual(c5({ supervision_stable: 'off', supervision_state: 'LOST' }), ['fail', 'No stable heartbeat (LOST)']);
  assert.deepEqual(c5({ supervision_stable: 'unavailable' }), ['unknown', 'Entity unavailable']);
});

test('FB-B2 outcome panels: the wording of every Save / Invalidate result, and the unknown-outcome guidance', () => {
  const env = card.makeFormatters({ locale: 'en-GB', timeZone: 'UTC' });
  const res = (name) => actResult(build(name).vm, env);
  const text = (r) => textNodes(r.html).join(' | ');
  assert.equal(actResult(build('idle_saved').vm, env), null);
  assert.equal(actResult(build('saving').vm, env), null, 'progress has its own view');
  assert.equal(actResult(build('ready_diff').vm, env), null);
  let r = res('saved_ok');
  assert.deepEqual([r.word, r.tone], ['SAVED', 'ok']);
  assert.match(text(r), /^Saved and verified this boot: generation 8, 12 Sept 2026, 14:23\. \| Generation \| 8 \| Saved \| 12 Sept 2026, 14:23 \| ID \| 7C5A0E91$/);
  // not verified (B2 still shows the old generation): the card does not claim verification
  const unverified = actResult(deriveModel({ ...scenarios.saved_ok, summary: scenarios.idle_saved.summary }, IDS), env);
  assert.match(text(unverified), /^The dongle reports the save\. Waiting for the saved profile to update\. \| Generation \| 8$/);
  r = res('save_refused_arm');
  assert.deepEqual([r.word, r.tone], ['SAVE REFUSED', 'warn']);
  assert.match(text(r), /^ECCO Fallback Profile Arm is not on \| Nothing was saved and the inverter was not changed\. The arm was turned off: review again before trying again\.$/);
  r = res('save_not_committed');
  assert.deepEqual([r.word, r.tone], ['SAVE NOT COMMITTED', 'bad']);
  assert.match(text(r), /Nothing changed: the previous profile is still in place\./);
  r = res('save_stale_witness');
  assert.match(text(r), /out of step with its generation record and cannot be used\. Review and save again\./);
  r = res('save_unknown');
  assert.deepEqual([r.word, r.tone], ['SAVE OUTCOME UNKNOWN', 'bad']);
  assert.match(text(r), /storage reported E105\/READ_ERROR; reboot the dongle \(when no temporary operation is active\) to re-verify; saving disabled until then/);
  assert.match(text(r), /Do not press Save again\. If a temporary operation \(Free Power, Dump to Grid, register 244 test\) is active or needs a decision, do not restart the dongle\. Otherwise restart the dongle to find out what was stored\.$/);
  r = res('invalidated_ok');
  assert.deepEqual([r.word, r.tone], ['INVALIDATED', 'ok']);
  assert.match(text(r), /Invalidated generation \| 7 \| Record is now generation \| 8$/);
  r = res('invalidate_refused');
  assert.deepEqual([r.word, r.tone], ['INVALIDATE REFUSED', 'warn']);
  assert.match(text(r), /^inverter busy; try again \| Nothing was changed\. The arm was turned off: arm again to try again\.$/);
  r = res('invalidate_stale');
  assert.match(text(r), /generation record advanced: g7 is now STALE \(unusable\) \| The profile record was not written, but its generation record advanced/);
  r = res('invalidate_unknown');
  assert.deepEqual([r.word, r.tone], ['INVALIDATE OUTCOME UNKNOWN', 'bad']);
  assert.match(text(r), /Treat the profile as unusable\. If a temporary operation .* do not restart the dongle\. Otherwise restart the dongle/);
  r = res('action_refused');
  assert.deepEqual([r.word, r.tone], ['REFUSED', 'warn']);
  assert.match(text(r), /unsupported action 'FOO' \| The dongle refused an action this card does not send\./);
  assert.equal(groupId('9C21B04E7D185F3A'), '9C21 B04E 7D18 5F3A');
  assert.equal(groupId('9c21b04e7d185f3a'), '—');
  assert.equal(groupId(null), '—');
});

// ===========================================================================
// FB-B2 card-fix: the findings of the independent safety audit (CARD-01 .. CARD-11)
// ===========================================================================
test('FB-B2 CARD-01: a supervision state that is shown and is not SUPERVISED fails the heartbeat prerequisite and check 5, whatever the stable entity says', () => {
  const heartbeatText = 'Home Assistant heartbeat is not stable; wait until the dashboard shows it healthy, then review and save again';
  for (const stable of ['unavailable', 'unknown', undefined, '', 'off', 'on']) {
    for (const state of ['LOST', 'SUSPECT', 'DEGRADED']) {
      const { vm, tv, gate } = gateFor('arm_on_ready', { supervision_stable: stable, supervision_state: state });
      const label = `stable ${String(stable)} / state ${state}`;
      const hb = itemOf(gate, 'heartbeat');
      assert.equal(hb.state, 'fail', label);
      assert.equal(hb.detail, stable === 'off' ? heartbeatText : supervisionStateText(state), label);
      assert.equal(gate.allowed, false, label);
      assert.equal(gate.allowedToArm, false, `${label}: Arm Save is not offered either`);
      assert.equal(gate.why, hb.detail, label);
      const c5 = buildChecks(vm, tv)[4];
      assert.equal(c5.state, 'fail', label);
      assert.equal(c5.detail, stable === 'off' ? `No stable heartbeat (${state})` : supervisionStateText(state), label);
      const rm = gateFor('ready_match', { supervision_stable: stable, supervision_state: state }, { armOnS: null });
      assert.deepEqual(armButtonState(rm.gate, rm.vm), { disabled: true, why: hb.detail }, `${label}: the Arm Save button says why`);
    }
  }
  assert.equal(supervisionStateText('LOST'), 'Supervision state is LOST, not SUPERVISED');
  // what the card cannot judge stays "unknown" and does not stop the save (the dongle checks it): no state shown, or SUPERVISED with no stable entity
  for (const [stable, state] of [['unavailable', 'unavailable'], ['unknown', undefined], [undefined, ''], ['unavailable', 'SUPERVISED']]) {
    const { vm, tv, gate } = gateFor('arm_on_ready', { supervision_stable: stable, supervision_state: state });
    assert.equal(itemOf(gate, 'heartbeat').state, 'unknown', `${stable}/${state}`);
    assert.equal(buildChecks(vm, tv)[4].state, 'unknown', `${stable}/${state}`);
    assert.equal(gate.allowed, true, `${stable}/${state}`);
  }
  assert.equal(gateFor('arm_on_ready', { supervision_stable: 'on', supervision_state: 'unavailable' }).gate.allowed, true, 'stable with no state shown: the dongle checks the state');
  assert.equal(itemOf(gateFor('arm_on_ready', { supervision_stable: 'on', supervision_state: 'SUPERVISED' }).gate, 'heartbeat').state, 'pass');
});

test('FB-B2 CARD-03: a READY candidate whose time left is not known is never saveable (exp -, 999, 121, abc)', () => {
  for (const exp of ['-', '999', '121', 'abc', '-5', '1e2']) {
    const review = scenarios.arm_on_ready.review.replace('exp=87', `exp=${exp}`);
    const { vm, tv, gate } = gateFor('arm_on_ready', { review });
    const label = `exp=${exp}`;
    assert.equal(vm.st, 'CANDIDATE_READY', label);
    assert.equal(vm.exp, null, label);
    assert.equal(tv.has, false, label);
    const fresh = itemOf(gate, 'fresh');
    assert.deepEqual([fresh.state, fresh.detail, fresh.required], ['unknown', 'Time left not known', true], label);
    assert.equal(gate.allowed, false, `${label}: with the arm on, Save is still not allowed`);
    assert.equal(gate.allowedToArm, false, label);
    assert.equal(gate.why, 'Time left not known', label);
    assert.deepEqual(armButtonState(gate, vm), { disabled: true, why: 'The arm is already on' }, label);
    const off = gateFor('ready_match', { review: scenarios.ready_match.review.replace(/exp=\d+/, `exp=${exp}`) }, { armOnS: null });
    assert.deepEqual(armButtonState(off.gate, off.vm), { disabled: true, why: 'Time left not known' }, `${label}: Arm Save says why`);
  }
});

test('FB-B2 CARD-03: the REPLACE CORRUPT variant follows the candidate (the B3 prior), never B1, in both directions', () => {
  // B1 says CORRUPT, the candidate was reviewed against a VALID prior: a plain save
  const plain = gateFor('arm_on_ready', { profile_state: 'CORRUPT' }).gate;
  assert.equal(plain.variant, 'save');
  assert.equal(plain.phrase, 'SAVE 5F3A9C21B04E7D18');
  assert.equal(plain.allowed, true);
  assert.equal(plain.effect.kind, 'replace');
  // B1 says VALID, the candidate's prior is CORRUPT: REPLACE CORRUPT
  const replace = gateFor('arm_on_ready', { review: scenarios.arm_on_ready.review.replace('prior=VALID', 'prior=CORRUPT') }).gate;
  assert.equal(replace.variant, 'replace_corrupt');
  assert.equal(replace.phrase, 'SAVE 5F3A9C21B04E7D18 REPLACE CORRUPT');
  assert.equal(replace.allowed, true);
  assert.equal(replace.effect.kind, 'replace_corrupt');
  // the same for every B1 class: the variant is a function of the prior alone
  for (const b1 of card.CLASS_NAMES) {
    assert.equal(gateFor('arm_on_ready', { profile_state: b1 }).gate.variant, 'save', `B1 ${b1} with a VALID prior`);
    assert.equal(gateFor('arm_on_ready', { profile_state: b1, review: scenarios.arm_on_ready.review.replace('prior=VALID', 'prior=CORRUPT') }).gate.variant, 'replace_corrupt', `B1 ${b1} with a CORRUPT prior`);
  }
});

test('FB-B2 CARD-05: the arm turning off is not an answer by itself; B3 or B9 answers at once, the arm only after the grace', () => {
  const keys = { review: 'r', b9: 'b', arm: 'a' };
  const vm = build('arm_on_ready').vm;
  const f0 = makeFlow('save', { id: REVIEW_ID, variant: 'save', effect: saveEffect(vm), vm, nowMs: T0, keys });
  assert.equal(f0.armOn, true);
  const snap = (over = {}) => ({ review: 'ready', b9Key: 'b', armState: true, nowMs: T0 + 100, ...over });
  assert.equal(advanceFlow(f0, snap({ armState: false })), f0, 'the arm-off echo, B3 and B9 unchanged: still pending');
  assert.equal(advanceFlow(f0, snap({ armState: false, review: 'available' })), null, 'B3 left CANDIDATE_READY: answered at once');
  assert.equal(advanceFlow(f0, snap({ armState: false, b9Key: 'b2' })), null, 'B9 changed: answered at once');
  assert.equal(advanceFlow(f0, snap({ armState: false, nowMs: T0 + ARM_OFF_GRACE_MS - 1 })), f0);
  assert.equal(advanceFlow(f0, snap({ armState: false, nowMs: T0 + ARM_OFF_GRACE_MS })), null);
  // only an arm that is OFF can answer; an arm that stays on or is unavailable never does
  for (const armState of [true, null]) assert.equal(advanceFlow(f0, snap({ armState, nowMs: T0 + ARM_OFF_GRACE_MS + 1000 })), f0, String(armState));
  // a request sent while the arm was not reported on is never answered by the arm
  const noArm = { ...f0, armOn: false };
  assert.equal(advanceFlow(noArm, snap({ armState: false, nowMs: T0 + ARM_OFF_GRACE_MS + 1000 })), noArm);
  // the timed-out and the rejected states end the same way, and not otherwise
  for (const state of ['timeout', 'unsure']) {
    const f = { ...f0, state };
    assert.equal(advanceFlow(f, snap({ armState: false })), f, state);
    assert.equal(advanceFlow(f, snap({ armState: false, nowMs: T0 + ARM_OFF_GRACE_MS })), null, state);
    assert.equal(advanceFlow(f, snap({ nowMs: T0 + 100 * ACT_PENDING_TIMEOUT_MS })), f, `${state}: time alone never ends it`);
  }
  assert.equal(ARM_OFF_GRACE_MS < ACT_PENDING_TIMEOUT_MS, true);
});

test('FB-B2 CARD-07: Save needs the candidate values on screen and a parsed saved-profile summary; no generation is derived from missing data', () => {
  const base = scenarios.arm_on_ready;
  // the candidate values (B5, B6): unavailable, malformed, or not a candidate view
  for (const patch of [{ review_slots: 'unavailable' }, { review_context: 'unavailable' }, { review_slots: 'garbage' }, { review_slots: base.review_slots.replace('v=CAND', 'v=NONE') }, { review_context: base.review_context.replace('v=CAND', 'v=SAVED') }]) {
    const { vm, gate } = gateFor('arm_on_ready', patch);
    const label = JSON.stringify(Object.keys(patch));
    assert.equal(vm.candOK, false, label);
    assert.equal(vm.eligible, true, `${label}: the firmware verdict alone says eligible - the card needs the values too`);
    const c = itemOf(gate, 'candidate');
    assert.deepEqual([c.state, c.detail, c.required], ['unknown', FLOW_TEXT.candValuesMissing, true], label);
    assert.equal(gate.allowed, false, label);
    assert.equal(gate.allowedToArm, false, label);
  }
  assert.equal(gateFor('arm_on_ready').vm.candOK, true);
  // the saved-profile summary (B2): unavailable or malformed
  for (const summary of ['unavailable', 'garbage', undefined]) {
    const { vm, gate } = gateFor('arm_on_ready', { summary });
    const label = String(summary);
    assert.equal(vm.b2, null, label);
    assert.equal(expectedGeneration(vm), null, label);
    assert.equal(gate.effect.gen, null, `${label}: no expected generation is printed`);
    assert.equal(gate.effect.sentence, `Replaces the saved profile. ${FLOW_TEXT.generationUnknown}`, label);
    const s = itemOf(gate, 'stored');
    assert.deepEqual([s.state, s.detail, s.required], ['unknown', FLOW_TEXT.summaryMissing, true], label);
    assert.equal(gate.allowed, false, label);
    assert.equal(gate.allowedToArm, false, label);
  }
  // a class that the summary must carry a generation for, with none; a lost profile with no witness generation
  assert.equal(expectedGeneration(deriveModel({ ...base, summary: base.summary.replace('g=7;', 'g=-;') }, IDS)), null, 'VALID with g=-');
  assert.equal(gateFor('arm_on_ready', { summary: base.summary.replace('g=7;', 'g=-;') }).gate.allowed, false);
  const lostBase = { ...base, review: base.review.replace('prior=VALID', 'prior=PROFILE_LOST') };
  assert.equal(expectedGeneration(deriveModel(lostBase, IDS)), 8, 'PROFILE_LOST with the witness generation');
  assert.equal(expectedGeneration(deriveModel({ ...lostBase, summary: lostBase.summary.replace('hw=7', 'hw=-') }, IDS)), null, 'PROFILE_LOST with no witness generation');
  assert.equal(expectedGeneration(deriveModel({ ...base, review: base.review.replace('prior=VALID', 'prior=NEW_CLASS') }, IDS)), null, 'an unrecognised class');
  // the table of what is derivable
  assert.equal(expectedGeneration(build('arm_on_ready').vm), 8);
  assert.equal(expectedGeneration(build('arm_on_first').vm), 1, 'nothing stored, a parsed summary: generation 1');
  assert.equal(expectedGeneration(build('arm_on_corrupt').vm), 8, 'the witness generation sets the base for a damaged profile');
  assert.equal(expectedGeneration(deriveModel({ ...scenarios.arm_on_first, summary: 'unavailable' }, IDS)), null, 'nothing stored, but no summary either: not known');
});

test('FB-B2 CARD-10: one entity id serves one key; the arm is never also a write arm or any other entity', () => {
  for (const other of ['free_power_arm', 'dump_arm', 'manual_arm']) {
    assert.throws(() => cfgWith({ arm: IDS[other] }), new RegExp(`entities\\.${other} repeats the entity id of entities\\.arm`), `arm = ${other}`);
    assert.throws(() => cfgWith({ [other]: IDS.arm }), new RegExp(`entities\\.${other} repeats the entity id of entities\\.arm`), `${other} = arm`);
  }
  assert.throws(() => cfgWith({ free_power_arm: IDS.dump_arm }), /entities\.dump_arm repeats the entity id of entities\.free_power_arm/);
  assert.throws(() => cfgWith({ manual_arm: IDS.free_power_arm }), /repeats the entity id/);
  assert.throws(() => validateConfig({ entities: { ...IDS, review: IDS.summary } }), /entities\.review repeats the entity id of entities\.summary/);
  assert.throws(() => validateConfig({ entities: { ...IDS, write_lock: IDS.configuration_online } }), /repeats the entity id/);
  assert.doesNotThrow(() => cfgWith(), 'distinct ids are fine');
  assert.doesNotThrow(() => validateConfig({ entities: { ...IDS_NO_ARMS } }));
  // defence in depth: a config object that did not come from validateConfig and names the arm twice allows no arm call and no execute call
  const ok = cfgWith();
  const forged = { ...ok, entities: { ...ok.entities, dump_arm: IDS.arm } };
  const exec = { domain: 'esphome', service: EXECUTE_SERVICE, data: { action: 'SAVE', target_id: REVIEW_ID, confirmation: `SAVE ${REVIEW_ID}` } };
  for (const call of [buildServiceCall('arm_on', ok), buildServiceCall('arm_off', ok), exec]) {
    assert.equal(isAllowedServiceCall(call, ok), true, JSON.stringify(call));
    assert.equal(isAllowedServiceCall(call, forged), false, JSON.stringify(call));
  }
  assert.equal(isAllowedServiceCall(buildServiceCall('review', ok), forged), true, 'Review does not depend on the arm');
});

test('FB-B2 CARD-11: "saved and verified" also needs the witness OK, no storage error and the matching last operation', () => {
  const base = scenarios.saved_ok;
  const verified = (patch) => deriveModel({ ...base, ...patch }, IDS).act.verified;
  const sum = (from, to) => ({ summary: base.summary.replace(from, to) });
  assert.equal(verified({}), true);
  for (const [from, to] of [['w=OK', 'w=LAG'], ['w=OK', 'w=MISS'], ['w=OK', 'w=CORR'], ['w=OK', 'w=UNR'], ['w=OK', 'w=ABS'], ['werr=-', 'werr=E102'], ['op=SAVE', 'op=INV'], ['op=SAVE', 'op=-']]) {
    assert.equal(verified(sum(from, to)), false, `${from} -> ${to}`);
  }
  assert.equal(verified(sum('op=SAVE', 'op=RC')), true, 'a REPLACE CORRUPT save publishes op=RC');
  assert.equal(verified({ summary: 'unavailable' }), false, 'no summary: nothing to verify');
  assert.equal(deriveAct(parseB9(base.last_result), 'VALID', 8).verified, false, 'no parsed summary passed: not verified');
  // an invalidate: op INV, witness OK, no storage error
  const invBase = scenarios.invalidated_ok;
  const verifiedInv = (patch) => deriveModel({ ...invBase, ...patch }, IDS).act.verified;
  const invSum = (from, to) => ({ summary: invBase.summary.replace(from, to) });
  assert.equal(verifiedInv({}), true);
  for (const [from, to] of [['w=OK', 'w=LAG'], ['werr=-', 'werr=E102'], ['op=INV', 'op=SAVE'], ['op=INV', 'op=RC'], ['op=INV', 'op=-']]) {
    assert.equal(verifiedInv(invSum(from, to)), false, `${from} -> ${to}`);
  }
  // the wording follows: unverified outcomes never say "Saved and verified" / "Invalidated:"
  const env = card.makeFormatters({ locale: 'en-GB', timeZone: 'UTC' });
  const textOf = (E) => textNodes(actResult(deriveModel(E, IDS), env).html).join(' | ');
  assert.match(textOf({ ...base, ...sum('w=OK', 'w=LAG') }), /^The dongle reports the save\. Waiting for the saved profile to update\. \| Generation \| 8$/);
  assert.match(textOf({ ...base, ...sum('werr=-', 'werr=E102') }), /^The dongle reports the save\./);
  assert.match(textOf({ ...invBase, ...invSum('op=INV', 'op=SAVE') }), /^The dongle reports the invalidation\. Waiting for the saved profile to update\. \| Invalidated generation \| 7 \| Record is now generation \| 8$/);
  assert.match(textOf(invBase), /^Invalidated: the profile can no longer be used\. Save a new profile to re-enable it\./);
  assert.doesNotMatch(textOf({ ...base, ...sum('w=OK', 'w=LAG') }), /verified/i);
});

test('FB-B2 CARD-03: the unknown-outcome guidance is exact: it never claims the save or the invalidate as done', () => {
  const env = card.makeFormatters({ locale: 'en-GB', timeZone: 'UTC' });
  assert.equal(FLOW_TEXT.saveUnknown, 'Do not press Save again. If a temporary operation (Free Power, Dump to Grid, register 244 test) is active or needs a decision, do not restart the dongle. Otherwise restart the dongle to find out what was stored.');
  assert.equal(FLOW_TEXT.invalidateUnknown, 'Treat the profile as unusable. If a temporary operation (Free Power, Dump to Grid, register 244 test) is active or needs a decision, do not restart the dongle. Otherwise restart the dongle to find out what was stored.');
  const save = actResult(build('save_unknown').vm, env);
  assert.deepEqual(textNodes(save.html), ['storage reported E105/READ_ERROR; reboot the dongle (when no temporary operation is active) to re-verify; saving disabled until then', FLOW_TEXT.saveUnknown]);
  const inv = actResult(build('invalidate_unknown').vm, env);
  assert.equal(textNodes(inv.html).length, 2);
  assert.equal(textNodes(inv.html)[1], FLOW_TEXT.invalidateUnknown);
  assert.match(textNodes(inv.html)[0], /^[^]*(unusable|outcome|reboot|storage)[^]*$/i);
  for (const t of [...textNodes(save.html), ...textNodes(inv.html)]) assert.doesNotMatch(t, /\b(was|has been|is now|were|have been) (saved|invalidated)\b|\bsaved and verified\b|\bsuccess/i, t);
});
