// Rendering tests: every scenario renders; wording hygiene; escaping; stepper; countdown; summary; a11y hooks.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import {
  card, scenarios, meta, IDS, T0, fmt, uiDefaults, build, renderScenario, allText, textNodes,
  cardRegexes, HAZARD_PATTERNS, NEVER_WORDS, cardDir,
} from './helpers.mjs';
import { MDocument, parseHtml } from './minidom.mjs';

const {
  renderAll, fillTime, timeTexts, timeView, makeAnchor, deriveModel, resolveSummaryView, planPatch,
  RECOVERY_TILES, RAW_ROWS, SENTENCE, WARNING_TEXT, KIND_TEXT, LD_TEXT, DF_TEXT, W_TEXT, STYLE, CARD_DEFS,
  blockerText, unusableSentence, priorBlockerText, priorReplaceNote, FALLBACK_BLOCKER, moreBlockers, REGS,
} = card;

const names = Object.keys(scenarios);
const html = (out) => Object.values(out.cards).map((c) => c.inner).join('');
const count = (s, re) => (s.match(re) || []).length;

// ---------------------------------------------------------------------------
// every scenario renders, in both detail states and across the countdown
// ---------------------------------------------------------------------------
test('every scenario renders all eight cards without throwing, at several moments', () => {
  assert.equal(CARD_DEFS.length, 8);
  for (const name of names) {
    for (const elapsedS of [0, 30, 100, 119, 400]) {
      for (const detailOpen of [false, true]) {
        const { out } = renderScenario(name, { elapsedS, ui: { detailOpen } });
        assert.deepEqual(Object.keys(out.cards), ['c1', 'c2', 'c3', 'c4', 'c5', 'c6', 'c7', 'c8'], name);
        for (const [id, c] of Object.entries(out.cards)) {
          assert.ok(c.inner.length > 20, `${name} ${id}`);
          assert.match(c.state, /^var\(--(ok|warn|bad|idle|busy|future)\)$/, `${name} ${id}`);
          assert.doesNotMatch(c.inner, /undefined|NaN|\[object|null</, `${name} ${id}`);
        }
      }
    }
  }
});

test('the scenario set covers every review state, profile state and checks outcome', () => {
  const seenReview = new Set();
  const seenProfile = new Set();
  for (const n of names) {
    const { vm } = build(n);
    seenReview.add(vm.review);
    seenProfile.add(vm.profile);
  }
  for (const r of ['available', 'reading', 'ready', 'notsaveable', 'mismatch', 'readerror', 'refused', 'expired', 'cleared', 'internal', 'unrecognised', 'unavailable']) {
    assert.ok(seenReview.has(r), `review state ${r}`);
  }
  for (const p of ['saved', 'notsaved', 'invalidated', 'unusable', 'unavailable']) assert.ok(seenProfile.has(p), `profile ${p}`);
  const classes = new Set(names.map((n) => scenarios[n].profile_state));
  for (const b1 of card.CLASS_NAMES) assert.ok(classes.has(b1), `B1 ${b1} has a fixture`);
});

// ---------------------------------------------------------------------------
// wording hygiene (energy-actions regexes, the two forbidden words)
// ---------------------------------------------------------------------------
function allStaticStrings() {
  const out = [];
  const push = (o) => {
    if (typeof o === 'string') out.push(o);
    else if (Array.isArray(o)) o.forEach(push);
    else if (o && typeof o === 'object') Object.values(o).forEach(push);
  };
  push(SENTENCE); push(WARNING_TEXT); push(KIND_TEXT); push(LD_TEXT); push(DF_TEXT); push(W_TEXT); push(RECOVERY_TILES); push(RAW_ROWS);
  push(card.FLOW_TEXT); push(card.GATE_LABEL); // FB-B2: the Save / Invalidate flow tables
  push(REGS.map((r) => r.name));
  for (const b1 of card.CLASS_NAMES) push(unusableSentence(b1, 7));
  // the "stored profile not trusted / not compared" texts (FW0): one per class, plus the two not-compared captions
  for (const b1 of card.CLASS_NAMES) push(card.untrustedSentence(b1));
  for (const b1 of card.CLASS_NAMES) push(card.savedSegmentNote({ profile: 'unusable', b1 }));
  push(card.notComparedNote(build('not_saveable_unreadable').vm));
  push(card.notComparedNote(build('ready_match', { E: { ...scenarios.ready_match, review_slots: scenarios.ready_match.review_slots.replace(/dx=\w+$/, 'dx=-') } }).vm));
  for (const code of ['244X', 'PWRL1', 'PWRH2', 'SOCH3', 'SRCG4', 'MODE5', 'BITS6', 'HHMM1', '243X', 'ZZZ']) push(blockerText(code, { reg244: 0, reg243: 5, slots: [] }));
  push(card.warningRows('W1,W2,W3,W4,W5,W6,W9', []).map((r) => r.text));
  push([priorBlockerText('UNREADABLE'), priorReplaceNote('CORRUPT'), FALLBACK_BLOCKER, moreBlockers(1), moreBlockers(5)]);
  return out;
}

test('wording hygiene: no card string matches an energy-actions regex or contains the two forbidden words', () => {
  const regexes = cardRegexes();
  assert.ok(regexes.length >= 10, `expected to parse the card regex literals, got ${regexes.length}`);
  const sources = new Set(regexes.map((r) => r.source));
  for (const s of ['freePowerState.ts', 'dumpState.ts', 'recoveryPresentation.ts']) assert.ok(sources.has(s), `regexes parsed from ${s}`);
  const patterns = [...regexes.map((r) => r.re), ...HAZARD_PATTERNS, ...NEVER_WORDS];
  const texts = new Set(allStaticStrings());
  for (const n of names) {
    for (const elapsedS of [0, 40, 119]) {
      const { out, tv } = renderScenario(n, { elapsedS, ui: { detailOpen: true } });
      for (const t of allText(out, tv)) texts.add(t);
    }
  }
  assert.ok(texts.size > 400, `too few strings scanned: ${texts.size}`);
  for (const t of texts) {
    for (const re of patterns) assert.doesNotMatch(t, re, `"${t}" matches ${re}`);
  }
});

test('wording hygiene also holds for the fixture B9 texts (they are what the card echoes)', () => {
  const regexes = cardRegexes().map((r) => r.re).concat(HAZARD_PATTERNS, NEVER_WORDS);
  for (const [n, s] of Object.entries(scenarios)) {
    for (const re of regexes) assert.doesNotMatch(s.last_result, re, `${n}: ${s.last_result}`);
  }
});

test('no status string starts with the words the busy classifiers key on', () => {
  for (const n of names) {
    const { out, tv } = renderScenario(n, { ui: { detailOpen: true } });
    for (const t of allText(out, tv)) assert.doesNotMatch(t, /^(restoring|starting|activation verify)/i, t);
  }
});

// ---------------------------------------------------------------------------
// escaping
// ---------------------------------------------------------------------------
test('hostile entity text never becomes markup', () => {
  const evil = '<img src=x onerror=alert(1)><script>alert(2)</script>"\'&';
  const E = { ...scenarios.ready_diff };
  for (const k of Object.keys(E)) E[k] = evil;
  E.last_result = `REVIEW REFUSED - ${evil}`;
  E.profile_state = evil;
  E.supervision_state = evil;
  const hostile = [
    E,
    { ...scenarios.ready_diff, last_result: `CANDIDATE READY - ${evil}` },
    { ...scenarios.mismatch, last_result: `REVIEW NOT COMPLETED - ${evil} register 1: <b> then </b>` },
    { ...scenarios.unusable, summary: `g=-;id=-;at=-;ld=${evil};df=${evil};w=${evil};hw=-;op=-;why=-;werr=-;us=-`.slice(0, 200) },
    { ...scenarios.ready_warn, review: scenarios.ready_warn.review.replace('W2,', '<W9>,') },
    { ...scenarios.refused, review: scenarios.refused.review.replace('FP:AC', '<b>:AC') },
    { ...scenarios.idle_saved, review: 'st=<x>;prior=-;exp=-;warn=-;obl=-;latch=-;sv=-' },
  ];
  for (const e of hostile) {
    const { out, tv } = renderScenario('ready_diff', { E: e, ui: { detailOpen: true, title: evil } });
    const markup = fillTime(out.header + html(out), tv);
    assert.doesNotMatch(markup, /<img|<script|<W9>|<x>/i);
    assert.ok(!markup.includes('register 1: <b> then </b>'), 'payload tags are escaped');
    assert.doesNotMatch(markup, /<[^>]*\son[a-z]+\s*=/i, 'no event-handler attribute can appear in a tag');
    assert.doesNotMatch(markup, /<[^>]*javascript:/i);
  }
});

test('esc handles every special character', () => {
  assert.equal(card.esc('<a href="x">&\'</a>'), '&lt;a href=&quot;x&quot;&gt;&amp;&#39;&lt;/a&gt;');
  assert.equal(card.esc(5), '5');
});

// ---------------------------------------------------------------------------
// controls: the only live control is Review (plus detail toggle, copy, view, more-info, scroll)
// ---------------------------------------------------------------------------
test('data-act values are a closed set; Review appears exactly once and only in the review card', () => {
  // FB-B2: arm / arm-invalidate / arm-cancel / save / invalidate are the guarded controls; "stay" marks a confirmation
  // panel or result block inside a tappable card, so a click on its text does nothing (it never opens more-info)
  const allowed = new Set(['review', 'toggle-detail', 'view', 'copy', 'more-info', 'goto-summary', 'arm', 'arm-invalidate', 'arm-cancel', 'save', 'invalidate', 'stay']);
  for (const n of names) {
    const { out } = renderScenario(n, { ui: { detailOpen: true } });
    const all = out.header + html(out) + Object.values(out.cards).map((c) => JSON.stringify(c.attrs)).join('');
    for (const m of all.matchAll(/data-act=\\?"([a-z-]+)\\?"/g)) assert.ok(allowed.has(m[1]), `${n}: ${m[1]}`);
    assert.equal(count(html(out), /data-act="review"/g), 1, n);
    assert.equal(count(out.cards.c3.inner, /data-act="review"/g), 1, n);
    for (const id of ['c1', 'c2', 'c4', 'c5', 'c6', 'c7', 'c8']) assert.doesNotMatch(out.cards[id].inner, /data-act="review"/, `${n} ${id}`);
  }
});

test('FB-B2: the inert Save placeholder is gone; Restore and Acknowledge controls still do not exist', () => {
  // FB-B2: the "Coming in FB-B2" placeholder and its chip are replaced by the guarded Arm Save flow (see the flow tests)
  for (const n of names) {
    const { out } = renderScenario(n, { ui: { detailOpen: true } });
    const m = html(out);
    assert.doesNotMatch(m, /Coming in FB-B2|Saving arrives in FB-B2/, n);
    // FB-B2: Arm and Invalidate controls exist now (only in their own states); Restore and Acknowledge never do
    assert.doesNotMatch(m, />\s*(Restore|Acknowledge)\b[^<]*<\/button>/i, n);
    assert.doesNotMatch(m, /<button[^>]*>[^<]*(Save Known-Good Profile|Restore Known-Good Profile|Restore Saved Profile|Acknowledge Recovery)/i, n);
    assert.doesNotMatch(m, /data-act="(restore|acknowledge)"/, n);
  }
});

test('recovery tiles are three ghosted, inert tiles with stage chips (FB-B2: the arm tile became the live Arm controls)', () => {
  const c8 = renderScenario('idle_saved').out.cards.c8.inner;
  // FB-B2: the Suspend / Arm ghost tile is gone (the arm is live in cards 1 and 4): three ghost tiles remain
  assert.equal(count(c8, /class="ghost"/g), 3);
  assert.equal(count(c8, /aria-disabled="true"/g), 3);
  assert.doesNotMatch(c8, /data-act|<button|tabindex/);
  for (const t of RECOVERY_TILES) assert.match(c8, new RegExp(`>${t.stage}<`));
  assert.deepEqual(RECOVERY_TILES.map((t) => [t.label, t.stage]), [
    ['Restore Saved Profile', 'FB-E'], ['Recovery Hold', 'FB-E'], ['Validated Resume', 'FB-F'],
  ]);
  assert.match(c8, /Reserved/);
  assert.match(STYLE, /\.ghost \{[^}]*opacity: \.45/);
  assert.match(STYLE, /\.ghost \{[^}]*dashed/);
  assert.match(STYLE, /#c8 \{ min-height: 140px/);
});

test('review button states render with aria-disabled and a reason (still focusable)', () => {
  const btn = (n, ui = {}) => /<button[^>]*data-act="review"[^>]*>/.exec(renderScenario(n, { ui }).out.cards.c3.inner)[0];
  assert.match(btn('idle_saved'), /aria-disabled="false"/);
  assert.doesNotMatch(btn('idle_saved'), /title=/);
  assert.match(btn('reading'), /aria-disabled="true"[^>]*title="Review in progress"/);
  assert.match(btn('unavailable'), /aria-disabled="true"/);
  assert.match(btn('refused_lock'), /title="Inverter bus busy - try again shortly"/);
  assert.match(btn('idle_saved', { pending: true }), /aria-disabled="true"[^>]*title="Review requested"/);
  for (const n of names) assert.doesNotMatch(btn(n), /\sdisabled(\s|>|=)/, `${n}: never a real disabled attribute (it would drop out of the tab order)`);
  assert.match(renderScenario('idle_saved').out.cards.c3.inner, /Reads the inverter twice \(4 reads\)\. Changes nothing\./);
});

test('review sentences follow design 5.3 headline table', () => {
  const head = (n) => {
    const r = renderScenario(n);
    const c3 = fillTime(r.out.cards.c3.inner, r.tv);
    return [/class="headline">([^<]*)</.exec(c3)[1], /<p class="sentence">([\s\S]*?)<\/p>/.exec(c3)[1].replace(/<[^>]+>/g, '')];
  };
  assert.deepEqual(head('idle_saved'), ['REVIEW AVAILABLE', 'Read the current inverter configuration and build a temporary candidate.']);
  assert.deepEqual(head('reading'), ['READING INVERTER', 'Read-only. Two passes, four reads, then a compare. Usually 2–3 s.']);
  assert.equal(head('ready_match')[0], 'CANDIDATE READY');
  assert.match(head('ready_match')[1], /^Both passes agree on all 31 registers\. Candidate expires in 1:2[0-9]\.$/);
  assert.deepEqual(head('not_saveable'), ['NOT SAVEABLE', 'Values read cleanly but cannot be saved in Fallback V1. See the candidate card.']);
  assert.equal(head('mismatch')[0], 'CONFIGURATION CHANGED DURING READ');
  assert.equal(head('mismatch')[1], 'live configuration changed during the read (register 257: 8000 then 5000); another controller may be editing - review again');
  assert.deepEqual(head('read_error'), ['REVIEW NOT COMPLETED', 'no response reading registers 241/53']);
  assert.deepEqual(head('refused'), ['REVIEW REFUSED', 'Free Power is active; live settings are a temporary overlay - end it first']);
  assert.deepEqual(head('expired'), ['CANDIDATE EXPIRED', 'The candidate expired after 120 s. Review again when ready.']);
  assert.deepEqual(head('cleared'), ['CANDIDATE CLEARED', 'a temporary operation started (Dump to Grid)']);
  assert.equal(head('internal')[0], 'INTERNAL STATE RESET');
  assert.match(head('internal')[1], /reboot required/);
  assert.deepEqual(head('unavailable'), ['NOT REPORTING', 'Fallback Profile entities are not available. Check firmware version.']);
  assert.match(head('malformed_review')[1], /cannot read/);
  assert.equal(head('st_unrecognised')[0], 'UNRECOGNISED STATE');
});

// ---------------------------------------------------------------------------
// stepper (design 7): no timer ever advances a sub-step
// ---------------------------------------------------------------------------
const stepper = (n, elapsedS = 0) => {
  const c3 = renderScenario(n, { elapsedS }).out.cards.c3.inner;
  const sp = /<div class="stepper[^"]*"[\s\S]*?<\/div><\/div>|<div class="stepper[^"]*"[\s\S]*?(?=<div class="slot">)/.exec(c3)[0];
  const steps = [...sp.matchAll(/<div class="step ([^"]*)"\s*(?:style="([^"]*)")?><span class="c"><\/span><span>([^<]*)<\/span><\/div>/g)].map((m) => ({ cls: m[1].trim(), colour: m[2] || '', label: m[3] }));
  return { raw: sp, steps };
};

test('stepper: state table of design 7', () => {
  const colours = (n) => stepper(n).steps.map((s) => (s.colour.match(/var\(--(\w+)\)/) || [])[1] || (s.cls || 'grey'));
  assert.deepEqual(colours('idle_saved'), ['grey', 'grey', 'grey', 'grey']);
  assert.deepEqual(colours('unavailable'), ['grey', 'grey', 'grey', 'grey']);
  assert.deepEqual(colours('reading'), ['busy', 'busy', 'busy', 'grey']);
  assert.match(stepper('reading').raw, /rail-busy/);
  assert.match(stepper('reading').raw, /4 reads in progress · read-only/);
  assert.equal(count(stepper('reading').raw, /pulse/g), 1, 'only the first dot pulses');
  assert.deepEqual(colours('ready_diff'), ['ok', 'ok', 'ok', 'ok']);
  assert.deepEqual(colours('not_saveable'), ['ok', 'ok', 'ok', 'warn']);
  assert.equal(stepper('not_saveable').steps[3].label, 'not saveable');
  assert.deepEqual(colours('mismatch'), ['ok', 'ok', 'bad', 'grey']);
  assert.equal(stepper('mismatch').steps[2].label, 'differs');
  assert.deepEqual(colours('read_error'), ['bad', 'bad', 'grey', 'grey']);
  assert.equal(stepper('read_error').steps[1].label, 'not completed');
  assert.match(stepper('read_error').raw, /Read of registers 241\/53 not completed\./, 'the block is named, the pass is not guessed');
  assert.equal(stepper('read_error').steps[0].label, 'Read pass 1', 'no pass number is attributed to the read problem');
  assert.equal(stepper('refused').steps[0].cls, 'slash');
  assert.equal(stepper('refused').steps[0].label, 'refused before reading');
  assert.equal(stepper('bus_busy').steps[0].cls, 'slash');
  assert.equal(stepper('expired').steps[3].cls, 'strike');
  assert.equal(stepper('expired').steps[3].label, 'expired');
  assert.equal(stepper('cleared').steps[3].label, 'cleared');
  assert.deepEqual(stepper('ready_diff').steps.map((s) => s.label), ['Read pass 1', 'Read pass 2', 'Compare', 'Candidate']);
});

test('stepper never advances sub-steps on a timer: identical markup at every moment', () => {
  for (const n of names) {
    const base = renderScenario(n, { elapsedS: 0 }).out.cards.c3.kids;
    for (const elapsedS of [1, 2, 3, 5, 8, 13]) {
      const kids = renderScenario(n, { elapsedS }).out.cards.c3.kids;
      assert.equal(kids[2], base[2], `${n}: stepper at +${elapsedS}s`);
    }
  }
  const idx = [0, 1, 2, 3, 4, 5];
  const a = renderScenario('reading', { elapsedS: 0 }).out.cards.c3.kids;
  const b = renderScenario('reading', { elapsedS: 3 }).out.cards.c3.kids;
  idx.forEach((i) => assert.equal(a[i], b[i], `reading kid ${i}`));
});

// ---------------------------------------------------------------------------
// countdown rendering (design 6)
// ---------------------------------------------------------------------------
test('countdown text, colours and captions per bucket; HTML only changes at bucket boundaries', () => {
  const at = (n, s) => renderScenario(n, { elapsedS: s });
  const txt = (n, s) => textNodes(at(n, s).out.cards.c4.inner, at(n, s).tv);
  // exp 112: plenty until 66 s have passed, soon from 67 s (45 s left), urgent from 98 s (14 s left)
  assert.ok(txt('ready_diff', 0).includes('1:51') || txt('ready_diff', 0).includes('1:52'));
  const marker = (s) => /<div class="count" style="--cc:([^"]*)">/.exec(at('ready_diff', s).out.cards.c3.kids[3])[1];
  assert.equal(marker(0), 'var(--text-2)');
  assert.equal(marker(66), 'var(--text-2)');
  assert.equal(marker(67), 'var(--warn)');
  assert.equal(marker(100), 'var(--warn)');
  const kidsAt = (s) => at('ready_diff', s).out.cards.c3.kids[3];
  assert.equal(kidsAt(0), kidsAt(30), 'a second ticking does not change the markup (only the placeholder text does)');
  assert.equal(kidsAt(0), kidsAt(66));
  assert.notEqual(kidsAt(66), kidsAt(67));
  assert.equal(kidsAt(67), kidsAt(80));
  assert.notEqual(kidsAt(80), kidsAt(98));
  assert.match(kidsAt(98), /<span class="n pulse" data-t="rem">/);
  assert.doesNotMatch(kidsAt(67), /class="n pulse"/);
  assert.match(kidsAt(0), /until the candidate expires/);
  assert.match(kidsAt(80), /expiring soon/);
  assert.match(kidsAt(113), /waiting for the firmware to confirm expiry/);
  assert.match(kidsAt(113), /--cc:var\(--idle\)/);
  assert.match(fillTime(kidsAt(113), at('ready_diff', 113).tv), /expiring…/);
  // the bar placeholder carries no width of its own (the tick writes it)
  assert.match(kidsAt(0), /<i data-tw><\/i>/);
  assert.equal(at('ready_diff', 0).tv.pct, 112 / 120 * 100);
});

test('"expiring…" at zero: the firmware still shows a candidate, so the card does not declare expiry', () => {
  const { out, tv } = renderScenario('ready_expiring', { elapsedS: 12 });
  assert.equal(tv.rem, 0);
  const c4 = fillTime(out.cards.c4.inner, tv);
  assert.match(c4, /Expires in<\/span><span class="v">expiring…<\/span>/);
  assert.doesNotMatch(c4, /Candidate expired\./, "the card never declares expiry: that is the firmware's call");
  assert.match(c4, /Expiring - waiting for the firmware/);
  // FB-B2: the row label is "Eligible to save"
  assert.match(c4, /Eligible to save<\/span><span class="v" style="color:var\(--warn\)">No \(expiring\)</);
  assert.match(fillTime(out.cards.c3.inner, tv), /Candidate is expiring; waiting for the firmware to confirm\./);
  assert.match(out.cards.c3.inner, /--state|class="head"/);
  // the firmware confirming expiry is what changes the card to the terminal state
  const e = renderScenario('expired');
  assert.match(e.out.cards.c4.inner, /CANDIDATE EXPIRED/);
  assert.doesNotMatch(e.out.cards.c4.inner, /data-t=/);
});

test('age, created, expires rows and the candidate ID copy button', () => {
  const { out, tv } = renderScenario('ready_diff', { elapsedS: 40 });
  const t = textNodes(out.cards.c4.inner, tv);
  const val = (k) => t[t.indexOf(k) + 1];
  assert.equal(val('Candidate ID'), '9C21 B04E 7D18 5F3A');
  assert.equal(val('Age'), '0:48');
  assert.equal(val('Expires in'), '1:12');
  assert.equal(val('Created'), '07:59:52', 'created = publish time minus what the firmware had consumed, rendered in the formatter time zone');
  // FB-B2: "Eligible for FB-B2 Save" became "Eligible to save"
  assert.equal(val('Eligible to save'), 'Yes');
  assert.equal(val('Would become'), 'generation 8 (replaces VALID generation 7)');
  assert.match(out.cards.c4.inner, /data-act="copy" data-copy-key="id"/);
  const none = textNodes(renderScenario('not_saveable').out.cards.c4.inner);
  assert.equal(none[none.indexOf('Candidate ID') + 1], '—');
  const first = textNodes(renderScenario('not_captured_cand').out.cards.c4.inner, build('not_captured_cand').tv);
  assert.equal(first[first.indexOf('Would become') + 1], 'generation 1');
  const lost = textNodes(renderScenario('profile_lost').out.cards.c4.inner);
  assert.ok(lost.includes('NO CANDIDATE'));
  const stale = renderScenario('ready_corrupt_prior');
  const st = textNodes(stale.out.cards.c4.inner, stale.tv);
  assert.equal(st[st.indexOf('Would become') + 1], 'generation 8 (stored profile CORRUPT)', 'generation base uses the witness high-water (hw=7)');
});

// ---------------------------------------------------------------------------
// cards 1 to 5 content
// ---------------------------------------------------------------------------
test('card 1 headline, colour and rows per profile state', () => {
  const c1 = (n) => renderScenario(n).out.cards.c1;
  const word = (n) => /class="headline">([^<]*)</.exec(c1(n).inner)[1];
  assert.equal(word('idle_saved'), 'SAVED');
  assert.equal(c1('idle_saved').state, 'var(--ok)');
  assert.equal(word('not_captured'), 'NOT SAVED');
  assert.equal(c1('not_captured').state, 'var(--idle)');
  assert.equal(word('invalidated'), 'INVALIDATED');
  assert.equal(c1('invalidated').state, 'var(--warn)');
  for (const n of ['unusable', 'unreadable', 'profile_lost', 'profile_stale', 'corrupt_domain', 'save_unconfirmed']) {
    assert.equal(word(n), 'UNUSABLE', n);
    assert.equal(c1(n).state, 'var(--bad)', n);
  }
  assert.equal(word('unavailable'), 'NOT REPORTING');
  assert.equal(c1('unavailable').state, 'var(--idle)');
  assert.doesNotMatch(c1('unavailable').inner, /class="rows"/);
  const t = textNodes(c1('idle_saved').inner);
  // FB-B2: the Invalidate control follows the rows. FB-B2 (AW-6): the tail is pinned EXACTLY - the six row texts, then the Arm Invalidate
  // button and its caption, and nothing else (the earlier prefix-only form let any extra text after the ID pass)
  assert.deepEqual(t.slice(t.indexOf('Generation')), ['Generation', '7', 'Saved', t[t.indexOf('Saved') + 1], 'ID', /id=([0-9A-F]{8})/.exec(scenarios.idle_saved.summary)[1], 'Arm Invalidate', card.FLOW_TEXT.armCaption]);
  assert.match(t[t.indexOf('Saved') + 1], /2026/);
  assert.match(renderScenario('unusable').out.cards.c1.inner, /witness: valid/);
  assert.match(renderScenario('unusable').out.cards.c1.inner, /defect: integrity check mismatch/);
  assert.match(renderScenario('unreadable').out.cards.c1.inner, /storage read error/);
  assert.match(renderScenario('profile_lost').out.cards.c1.inner, /last known generation 7/);
  // FB-B2: saving exists, so the witness note no longer says "(FB-B2)"
  assert.match(renderScenario('witness_lag').out.cards.c1.inner, /lagging behind the record - saving again would repair it/);
  const unrec = renderScenario('idle_saved', { E: { ...scenarios.idle_saved, profile_state: 'WOBBLY' } }).out.cards.c1.inner;
  assert.match(unrec, /Unrecognised Fallback Profile state &#39;WOBBLY&#39; — check that firmware and dashboard versions match\./);
  assert.match(renderScenario('idle_saved', { E: { ...scenarios.idle_saved, summary: scenarios.idle_saved.summary.replace('at=1789222500', 'at=0') } }).out.cards.c1.inner, /\(capture time unknown\)\./);
});

test('card 1 whole-card tap and keyboard entry open the more-info of the profile entity', () => {
  const c1 = renderScenario('idle_saved').out.cards.c1;
  assert.deepEqual(c1.attrs, { 'data-act': 'more-info', 'data-ent': 'profile_state' });
  assert.match(c1.inner, /data-act="more-info" data-ent="profile_state" data-fk="more-c1"/);
  assert.deepEqual(renderScenario('idle_saved').out.cards.c2.attrs, {}, 'card 2 is only tappable when a candidate exists');
  assert.deepEqual(renderScenario('ready_diff').out.cards.c2.attrs, { 'data-act': 'goto-summary' });
});

test('card 2 colour, icon and chips', () => {
  const c2 = (n) => renderScenario(n).out.cards.c2;
  assert.equal(c2('ready_match').state, 'var(--ok)');
  assert.equal(c2('ready_diff').state, 'var(--warn)');
  assert.equal(c2('reading').state, 'var(--busy)');
  assert.equal(c2('idle_saved').state, 'var(--idle)');
  assert.equal(count(c2('ready_diff').inner, /class="chip warn"/g), 2);
  assert.equal(count(c2('ready_warn').inner, /class="chip warn"/g), 4, 'three names plus "+4 more"');
  assert.match(c2('ready_warn').inner, /\+4 more/);
  assert.match(c2('reading').inner, /dot pulse/);
  const t = textNodes(c2('ready_diff').inner, build('ready_diff', { elapsedS: 5 }).tv);
  assert.equal(t[t.length - 1], 'Basis: review 0:13 ago');
  assert.equal(textNodes(c2('idle_saved').inner).slice(-1)[0], 'Basis: none');
});

test('card 5: footer sentences and tone', () => {
  const c5 = (n, s = 0) => renderScenario(n, { elapsedS: s }).out.cards.c5;
  // FB-B2: with the arm entity configured and off, a clean candidate says the save is allowed once the arm is on
  assert.match(c5('ready_match').inner, /<div class="foot ok">Save is allowed once the arm is on: use Arm Save in the candidate card\.<\/div>/);
  // FB-B2 (CARD-08), before: `c5('arm_on_ready')` (no intent) said "Save is armed: confirm it in the candidate card". The candidate card opens its confirmation
  // only for an arm this card switched on for a save, so card 5 says "armed" only then; any other arm that is on gets its own sentence and a warning tone
  const armedFor = (intent) => renderScenario('arm_on_ready', { armOnS: 3, elapsedS: 10, ui: { intent } }).out.cards.c5;
  assert.match(armedFor('save').inner, /<div class="foot ok">Save is armed: confirm it in the candidate card\.<\/div>/);
  assert.equal(armedFor('save').state, 'var(--ok)');
  for (const [intent, sentence] of [[null, 'The arm was not turned on from this card. Turn it off and arm again.'], ['sent', 'The arm was used by your request. Turn it off and arm again.'], ['invalidate', 'The arm is set for Invalidate (see the Saved profile card). Turn it off to save instead.']]) {
    const c = armedFor(intent);
    assert.ok(c.inner.includes(`<div class="foot warn">${card.esc(sentence)}</div>`), String(intent));
    assert.doesNotMatch(c.inner, /Save is armed/, String(intent));
    assert.equal(c.state, 'var(--warn)', String(intent));
  }
  assert.equal(c5('ready_match').state, 'var(--ok)');
  assert.match(c5('not_saveable').inner, /<div class="foot bad">Save would be refused: Profile values valid for Fallback V1\.<\/div>/);
  assert.equal(c5('not_saveable').state, 'var(--bad)');
  assert.match(c5('ready_nosup').inner, /Save would be refused: Supervision stable\./);
  assert.match(c5('ready_nosup').inner, /No stable heartbeat \(SUSPECT\)/);
  assert.match(c5('ready_nosup').inner, /Not NTP-synchronised this boot; a save would be refused/);
  assert.match(c5('idle_saved').inner, /Review first\. Checks 1–4 are evaluated at Review; 5–6 are live\./);
  assert.equal(c5('idle_saved').state, 'var(--idle)');
  assert.equal(c5('unavailable').state, 'var(--idle)');
  assert.doesNotMatch(c5('unavailable').inner, /class="foot|Review first/);
  assert.equal(c5('ready_warn').state, 'var(--warn)');
  assert.match(c5('not_saveable_unreadable').inner, /Save would be refused: the stored profile is UNREADABLE \(see candidate\)\./);
  assert.match(c5('transient_op').inner, /Dump to Grid is restoring/);
  // FB-B2: the firmware refuses a save over ANY non-clear obligation (G15 / G16), a transient one too, so the footer
  // says so and the card tone is red (check 4 itself stays a warning)
  assert.equal(c5('transient_op').state, 'var(--bad)');
  assert.match(c5('transient_op').inner, /<div class="foot bad">Save would be refused: No temporary operation active\.<\/div>/);
  assert.match(c5('ready_diff', 67).inner, /expiring soon/);
  const rows = [...c5('ready_match').inner.matchAll(/<div class="check (\w+)">/g)].map((m) => m[1]);
  assert.deepEqual(rows, ['pass', 'pass', 'pass', 'pass', 'pass', 'pass']);
  assert.match(c5('ready_match').inner, /title="Free Power: CA \(no record stored\); Dump to Grid: CM \(clear marker\)/);
});

test('top bar badges: supervision, NTP and write lock from the configured entities', () => {
  const header = (n, ui) => renderScenario(n, { ui }).out.header;
  assert.match(header('ready_diff'), /Supervision <span class="dot" style="background:var\(--ok\)"><\/span> stable/);
  assert.match(header('ready_diff'), /NTP <span class="dot" style="background:var\(--ok\)"><\/span> synced/);
  assert.match(header('ready_diff'), /Write lock <span class="dot" style="background:var\(--ok\)"><\/span> free/);
  assert.match(header('ready_nosup'), /Supervision <span class="dot" style="background:var\(--warn\)"><\/span> suspect/);
  assert.match(header('ready_nosup'), /NTP <span class="dot" style="background:var\(--warn\)"><\/span> not synced/);
  assert.match(header('refused_lock'), /Write lock <span class="dot" style="background:var\(--warn\)"><\/span> held/);
  assert.equal(count(header('unavailable'), /unavailable/g), 3);
  assert.equal(header('ready_diff', { showHeader: false }), '');
  assert.match(header('ready_diff', { title: 'Custom title' }), /Custom title/);
  assert.match(header('ready_diff'), /role="group" aria-label="Safety signals"/);
});

test('configuration polling offline is a hint under the button, not a gate', () => {
  const c3 = renderScenario('config_offline').out.cards.c3.inner;
  assert.match(c3, /Configuration polling is offline - a review may not complete\./);
  assert.match(c3, /aria-disabled="false"/);
  assert.doesNotMatch(renderScenario('idle_saved').out.cards.c3.inner, /Configuration polling/);
});

// ---------------------------------------------------------------------------
// card 6 summary
// ---------------------------------------------------------------------------
test('summary: source selector rules, default view, empty state', () => {
  const vm = (n) => build(n).vm;
  assert.equal(resolveSummaryView(vm('ready_diff'), 'auto'), 'cand');
  assert.equal(resolveSummaryView(vm('idle_saved'), 'auto'), 'saved');
  assert.equal(resolveSummaryView(vm('unavailable'), 'auto'), 'none');
  assert.equal(resolveSummaryView(vm('ready_diff'), 'saved'), 'saved');
  assert.equal(resolveSummaryView(vm('idle_saved'), 'cand'), 'saved', 'a candidate choice falls back when the candidate is gone');
  assert.equal(resolveSummaryView(vm('not_captured'), 'saved'), 'none');
  assert.equal(resolveSummaryView(vm('not_captured_cand'), 'saved'), 'cand');
  const seg = (n, view = 'auto') => renderScenario(n, { ui: { view } }).out.cards.c6.inner;
  assert.match(seg('idle_saved'), /data-view="cand"[^>]*aria-pressed="false" aria-disabled="true"[^>]*>Candidate<small>no candidate<\/small>/);
  assert.match(seg('idle_saved'), /data-view="saved"[^>]*aria-pressed="true" aria-disabled="false">Saved profile g7</);
  assert.match(seg('not_captured_cand'), /data-view="saved"[^>]*aria-disabled="true"[^>]*>Saved profile<small>no saved profile<\/small>/);
  assert.match(seg('not_captured'), /Nothing to show yet\. Review the current configuration to see it here\./);
  assert.doesNotMatch(seg('not_captured'), /<table/);
});

test('summary: settings strip, slot table, diff markers only in the candidate view', () => {
  const cand = renderScenario('ready_diff').out.cards.c6.inner;
  assert.equal(count(cand, /class="diff"/g), 3, 'slot 2 power, slot 4 source, grid-charge current');
  assert.match(cand, /5000 W<span class="was">◀ 500 W<\/span>/);
  assert.match(cand, /Grid<span class="was">◀ None<\/span>/);
  assert.match(cand, /185 A<span class="was">◀ 150 A<\/span>/);
  assert.match(cand, /<div class="legend">◀ = differs from saved profile<\/div>/);
  const saved = renderScenario('ready_diff', { ui: { view: 'saved' } }).out.cards.c6.inner;
  assert.equal(count(saved, /class="diff"/g), 0);
  assert.doesNotMatch(saved, /legend/);
  assert.match(saved, /Values stored in the saved profile \(generation 7\)\./);
  const match = renderScenario('ready_match').out.cards.c6.inner;
  assert.equal(count(match, /class="diff"/g), 0);
  assert.doesNotMatch(match, /legend/);
  const tiles = textNodes(match);
  assert.deepEqual(tiles.slice(tiles.indexOf('Export mode'), tiles.indexOf('Export mode') + 8), ['Export mode', 'Zero Export', 'Energy model', 'Load First', 'Grid charging', 'On', 'TOU schedule', 'On']);
  assert.match(match, /Not restored by Fallback V1: grid-charge current 150 A · export limit 8000 \(not evidence of export limitation\) · solar export on/);
  assert.match(match, /Slot times form a valid 24 h ring ✓/);
  assert.match(renderScenario('ready_w6').out.cards.c6.inner, /Slot times are not a valid 24 h ring/);
  assert.equal(count(renderScenario('ready_ctx_diff').out.cards.c6.inner, /class="diff"/g), 1);
  assert.match(renderScenario('ready_ctx_diff').out.cards.c6.inner, /19:30–23:45<span class="was">◀ 19:00<\/span>/);
  const rows = [...match.matchAll(/<tr><td class="num">(\d)<\/td><td>([^<]*)<\/td>/g)].map((m) => [m[1], m[2]]);
  assert.deepEqual(rows, [['1', '00:00–05:30'], ['2', '05:30–09:00'], ['3', '09:00–16:00'], ['4', '16:00–19:00'], ['5', '19:00–23:45'], ['6', '23:45–00:00']]);
  assert.equal(count(match, /class="hide-narrow"/g), 7, 'Mode column header plus six cells');
  assert.equal(count(match, /class="caption mode-fold"/g), 6, 'mode is folded under Source on narrow cards');
  assert.match(renderScenario('corrupt_domain', { ui: { view: 'saved' } }).out.cards.c6.inner, /This stored profile is CORRUPT_DOMAIN and cannot be used\./);
  assert.match(renderScenario('corrupt_domain', { ui: { view: 'saved' } }).out.cards.c6.inner, /65535 W/);
});

// ---------------------------------------------------------------------------
// card 7 advanced
// ---------------------------------------------------------------------------
test('advanced: collapsed by default, toggle labels, 31 rows, eight raw strings, obligation vector, latch', () => {
  const closed = renderScenario('ready_diff', { ui: { detailOpen: false } }).out.cards.c7.inner;
  assert.match(closed, /aria-expanded="false"[^>]*>▸ Show technical detail</);
  assert.doesNotMatch(closed, /<table/);
  const open = renderScenario('ready_diff', { ui: { detailOpen: true } }).out.cards.c7.inner;
  assert.match(open, /aria-expanded="true"[^>]*>▾ Hide technical detail</);
  assert.equal(count(open, /<tr><td class="mono">\d+<\/td>/g), 31);
  const regs = [...open.matchAll(/<tr><td class="mono">(\d+)<\/td>/g)].map((m) => Number(m[1]));
  assert.deepEqual(regs, REGS.map((r) => r.reg));
  assert.deepEqual(RAW_ROWS.map((r) => r.label), ['B2 Summary', 'B3 Review', 'B4 Review ID', 'B5 Review Slots', 'B6 Review Context', 'B7 Slots', 'B8 Context', 'B9 Last Action-Result']);
  assert.equal(count(open, /data-copy-key="(summary|review|review_id|review_slots|review_context|saved_slots|saved_context|last_result)"/g), 8);
  for (const r of RAW_ROWS) assert.match(open, new RegExp(`<small>${IDS[r.key].replace(/\./g, '\\.')}</small>`), `${r.key} shows its configured id`);
  assert.match(open, /Pass 1 and pass 2 agreed on all 31 registers; the firmware publishes the agreed words once\./);
  assert.match(open, /FP:CA/.source ? /Free Power<\/span><code>CA \(no record stored\)<\/code>/ : /x/);
  assert.match(open, /Probe latch<\/span><code>none \(-\)<\/code>/);
  assert.match(renderScenario('refused_latch', { ui: { detailOpen: true } }).out.cards.c7.inner, /Probe latch<\/span><code>Free Power \(FP\)<\/code>/);
  assert.match(renderScenario('idle_saved', { ui: { detailOpen: true } }).out.cards.c7.inner, /none yet - evaluated when a review runs/);
  assert.match(renderScenario('unavailable', { ui: { detailOpen: true } }).out.cards.c7.inner, /<code data-raw="review">unavailable<\/code>/);
  const miss = { ...scenarios.idle_saved }; delete miss.summary;
  assert.match(renderScenario('idle_saved', { E: miss, ui: { detailOpen: true } }).out.cards.c7.inner, /\(entity not found\)/);
  assert.match(open, /<th scope="col" class="num">Saved g7<\/th>/);
});

test('advanced pass columns render the design 5.7 rule', () => {
  const rows = (n) => {
    const open = renderScenario(n, { ui: { detailOpen: true } }).out.cards.c7.inner;
    return [...open.matchAll(/<tr><td class="mono">(\d+)<\/td><td>[^<]*<\/td><td>.*?<\/td><td class="num mono">([^<]*)<\/td><td class="num mono">([^<]*)<\/td>/g)].map((m) => [Number(m[1]), m[2], m[3]]);
  };
  assert.ok(rows('ready_diff').every(([, a, b]) => a === b && a !== '—'));
  const mm = rows('mismatch');
  assert.deepEqual(mm.filter(([, a]) => a !== '—'), [[257, '8000', '5000']]);
  assert.match(renderScenario('mismatch', { ui: { detailOpen: true } }).out.cards.c7.inner, /The firmware reports the first differing register only\./);
  assert.ok(rows('idle_saved').every(([, a, b]) => a === '—' && b === '—'));
  assert.ok(rows('read_error').every(([, a, b]) => a === '—' && b === '—'));
});

// ---------------------------------------------------------------------------
// a11y hooks and responsive CSS
// ---------------------------------------------------------------------------
test('live regions: headline and last action are polite; the countdown is not announced', () => {
  const c3 = renderScenario('ready_diff').out.cards.c3;
  assert.equal(c3.kids.length, 6);
  assert.equal(count(c3.inner, /aria-live="polite"/g), 2);
  assert.match(c3.kids[1], /^<div class="live" data-live="head" aria-live="polite">/);
  assert.match(c3.kids[5], /^<div class="last" data-live="last" aria-live="polite"/);
  assert.match(c3.kids[1], /<span aria-live="off">Candidate expires in <span data-t="rem"><\/span>\.<\/span>/);
  assert.doesNotMatch(c3.kids[3] + c3.kids[4], /aria-live/, 'the countdown block and the button are outside any live region');
  assert.equal(count(c3.inner, /aria-live/g), 3);
  assert.match(c3.kids[2], /role="group" aria-label="Review progress: Candidate ready"/);
});

test('every card keeps a stable kid structure so the review live regions persist', () => {
  const shapes = new Set(names.map((n) => renderScenario(n).out.cards.c3.kids.length));
  assert.deepEqual([...shapes], [6]);
  const live = (n) => renderScenario(n).out.cards.c3.kids.filter((k) => /data-live=/.test(k)).length;
  for (const n of names) assert.equal(live(n), 2, n);
});

test('planPatch keeps, updates live regions in place, replaces, or asks for a full replace', () => {
  const a = ['<div>1</div>', '<div class="live" data-live="head" aria-live="polite">x</div>', '<div>3</div>'];
  assert.deepEqual(planPatch(a, a.slice()), ['keep', 'keep', 'keep']);
  assert.deepEqual(planPatch(a, ['<div>1</div>', '<div class="live" data-live="head" aria-live="polite">y</div>', '<div>3b</div>']), ['keep', 'live', 'replace']);
  assert.deepEqual(planPatch(a, ['<div>1b</div>', '<div class="x" data-live="other">y</div>', '<div>3</div>']), ['replace', 'replace', 'keep']);
  assert.equal(planPatch(a, a.slice(0, 2)), null);
  assert.equal(planPatch(null, a), null);
  assert.equal(planPatch(a, null), null);
  // across two real renders of the review card: state change updates both live regions in place
  const r1 = renderScenario('ready_diff').out.cards.c3.kids;
  const r2 = renderScenario('expired').out.cards.c3.kids;
  const plan = planPatch(r1, r2);
  assert.equal(plan[1], 'live');
  assert.equal(plan[5], 'live');
  assert.equal(planPatch(r1, renderScenario('ready_diff', { elapsedS: 30 }).out.cards.c3.kids).every((o) => o === 'keep'), true);
});

test('CSS carries the responsive, motion and focus rules of the design', () => {
  assert.match(STYLE, /container-type: inline-size; container-name: fbr/);
  assert.match(STYLE, /@container fbr \(max-width: 1100px\)/);
  assert.match(STYLE, /@container fbr \(max-width: 700px\)/);
  assert.match(STYLE, /@container \(max-width: 620px\)/);
  assert.match(STYLE, /@container \(max-width: 420px\)/);
  assert.match(STYLE, /#c3 \{ order: -1; \}/);
  assert.match(STYLE, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(STYLE, /button:focus-visible/);
  assert.match(STYLE, /outline: 2px solid color-mix\(in srgb, var\(--busy\) 60%, transparent\)/);
  assert.match(STYLE, /--ok: #55e58e; --warn: #ffbd3d; --bad: #ff6376; --idle: #6d7b91; --busy: #42aaff; --future: #b8adff;/);
  assert.match(STYLE, /--card: #0d1728; --card-hi: #111c30; --card-lo: #0b1424;/);
  assert.match(STYLE, /border-radius: 18px/);
  assert.match(STYLE, /box-shadow: 0 10px 30px rgba\(0,0,0,\.22\)/);
  assert.match(STYLE, /\.scrollx \{ overflow-x: auto;/);
  assert.match(STYLE, /@supports not \(color: color-mix/);
  assert.doesNotMatch(STYLE, /@media \(max-width/, 'breakpoints are container queries, not viewport media queries');
  assert.doesNotMatch(STYLE, /https?:\/\//, 'no network resources');
});

test('the card source is self-contained: no imports, no fetch, no network, no eval', () => {
  const src = readFileSync(path.join(cardDir, 'ecco-fallback-recovery-card.js'), 'utf8');
  assert.doesNotMatch(src, /^\s*import\s/m);
  assert.doesNotMatch(src, /\bimport\s*\(/);
  assert.doesNotMatch(src, /\bfetch\s*\(|XMLHttpRequest|WebSocket|sendBeacon|eval\s*\(|new Function|document\.write|innerHTML\s*\+=/);
  assert.doesNotMatch(src, /https?:\/\//);
});

test('time placeholders: fillTime replaces them and nothing else', () => {
  const tv = timeView(makeAnchor({ exp: 75, lastChangedMs: T0, nowMs: T0 }), T0 + 5000);
  assert.equal(fillTime('<span data-t="rem"></span>|<span class="n" data-t="age"></span>|<span data-t="zzz"></span>', tv),
    '<span data-t="rem">1:10</span>|<span class="n" data-t="age">0:50</span>|<span data-t="zzz"></span>');
  // FB-B2: the arm countdown is a third placeholder
  assert.deepEqual(timeTexts(timeView(null, T0)), { rem: '—', age: '—', arm: '—' });
});

test('every fixture entity string stays within the 200 character cap', () => {
  for (const [n, s] of Object.entries(scenarios)) {
    for (const [k, v] of Object.entries(s)) {
      if (['summary', 'review', 'review_slots', 'review_context', 'saved_slots', 'saved_context', 'last_result'].includes(k)) {
        assert.ok(v.length <= 200, `${n}.${k} is ${v.length} chars`);
      }
    }
  }
});

test('meta has an entry per scenario with a label', () => {
  for (const n of names) assert.ok(meta[n] && typeof meta[n].label === 'string' && meta[n].expect, n);
});

// ---------------------------------------------------------------------------
// review round pins (RD3-RD6, RD9): motion, narrow layout, touch targets, card 7 structure, no second write path
// ---------------------------------------------------------------------------
/** The text between the braces of the first `head { ... }` block, found by brace matching (css has no comments left in it). */
function blockAfter(css, head) {
  const at = css.indexOf(head);
  if (at < 0) return null;
  const open = css.indexOf('{', at);
  let depth = 0;
  for (let i = open; i < css.length; i += 1) {
    if (css[i] === '{') depth += 1;
    else if (css[i] === '}') {
      depth -= 1;
      if (depth === 0) return { body: css.slice(open + 1, i), start: at, end: i + 1 };
    }
  }
  return null;
}
const stripComments = (css) => css.replace(/\/\*[\s\S]*?\*\//g, '');
/** Flat `selector { declarations }` rules of a stylesheet fragment (nested at-rule heads are skipped, their inner rules are listed). */
function rulesOf(css) {
  const out = [];
  for (const m of css.matchAll(/([^{}@]+)\{([^{}]*)\}/g)) {
    const sel = m[1].trim();
    if (!sel || /^(from|to|\d+%)/.test(sel)) continue;
    out.push({ selectors: sel.split(',').map((x) => x.trim().replace(/\s+/g, ' ')), body: m[2] });
  }
  return out;
}
const CSS = stripComments(STYLE);
const REDUCED = blockAfter(CSS, '@media (prefers-reduced-motion: reduce)');
const OUTSIDE_REDUCED = CSS.slice(0, REDUCED.start) + CSS.slice(REDUCED.end);

test('RD3: reduced motion stops every animated element: each animated selector is named in the reduced-motion block, plus a universal safety net', () => {
  const animated = new Set();
  for (const r of rulesOf(OUTSIDE_REDUCED)) {
    if (/(^|[;\s])(animation|transition)\s*:\s*(?!none)/.test(r.body)) r.selectors.forEach((s) => animated.add(s));
  }
  // FB-B2: .spin (the Save progress spinner) is the one new animated selector; it is also in the reduced-motion block
  const expected = ['.dot.pulse', '.step.on.pulse .c', '.count .n.pulse', '.sk', '.rail-busy .step.on::before', '.bar > i', '.spin'];
  for (const s of expected) assert.ok(animated.has(s), `the stylesheet animates ${s}`);
  assert.deepEqual([...animated].sort(), [...expected].sort(), 'no other selector animates (add it to the reduced-motion block when one does)');
  const reduced = rulesOf(REDUCED.body);
  const offs = new Set();
  for (const r of reduced) if (/(animation|transition)\s*:\s*none/.test(r.body)) r.selectors.forEach((s) => offs.add(s));
  for (const s of animated) assert.ok(offs.has(s), `${s} is switched off under prefers-reduced-motion`);
  // the stepper dot is the one the first version missed: its rule is on the child of .step, not on .pulse itself
  assert.ok(offs.has('.step.on.pulse .c'));
  // universal rule: any element, pseudo-elements included, with both properties off
  for (const u of ['*', '*::before', '*::after']) assert.ok(offs.has(u), `${u} is in the universal rule`);
  const universal = reduced.find((r) => r.selectors.includes('*'));
  assert.match(universal.body, /animation:\s*none\s*!important/);
  assert.match(universal.body, /transition:\s*none\s*!important/);
  // the skeleton keeps its static bar (no gradient) and the JS fallbacks honour the same preference
  assert.match(REDUCED.body, /\.sk \{ background-image: none; \}/);
  const src = readFileSync(path.join(cardDir, 'ecco-fallback-recovery-card.js'), 'utf8');
  assert.match(src, /matchMedia\('\(prefers-reduced-motion: reduce\)'\)/, 'smooth scrolling is skipped too');
});

test('RD5: the narrow-card .diff rules are scoped to table cells and tiles, so the info sentence stays in one piece', () => {
  const narrow = blockAfter(CSS, '@container (max-width: 420px)');
  assert.ok(narrow, 'the 420 px container block exists');
  const diffRules = rulesOf(narrow.body).filter((r) => r.selectors.some((s) => s.includes('.diff')));
  assert.ok(diffRules.length >= 2);
  for (const r of diffRules) {
    for (const s of r.selectors) assert.match(s, /^(td|\.tile) \.diff( \.was)?$/, `scoped selector: ${s}`);
  }
  // structure: the diff marker inside the info line is in neither a table cell nor a tile
  const doc = new MDocument();
  const holder = doc.createElement('div');
  parseHtml(renderScenario('ready_diff').out.cards.c6.inner, doc).forEach((n) => holder.appendChild(n));
  const diffs = holder.querySelectorAll('.diff');
  assert.equal(diffs.length, 3);
  const where = diffs.map((d) => (d.closest('td') ? 'td' : d.closest('.tile') ? 'tile' : d.closest('.info') ? 'info' : 'other'));
  assert.deepEqual(where.sort(), ['info', 'td', 'td']);
  // and the wide rules keep the amber bar and the inline "was" value
  assert.match(OUTSIDE_REDUCED, /\.diff \{ border-left: 3px solid var\(--warn\); padding-left: 8px; \}/);
});

test('RD9: the source selector and the technical-detail toggle are 44 px high for every pointer, not only under pointer: coarse', () => {
  const coarse = blockAfter(CSS, '@media (pointer: coarse)');
  const outsideCoarse = CSS.slice(0, coarse.start) + CSS.slice(coarse.end);
  const rule = (sel) => rulesOf(outsideCoarse).find((r) => r.selectors.includes(sel));
  assert.match(rule('.seg button').body, /min-height:\s*44px/);
  assert.match(rule('.toggle').body, /min-height:\s*44px/);
  assert.match(rule('.btn').body, /min-height:\s*44px/);
  assert.doesNotMatch(coarse.body, /\.seg button|\.toggle/, 'nothing left for the coarse-pointer block to add');
  // slot-table rows are 30 px like the mockup (its tables ignore the inherited 1.45 line height) and buttons inherit it
  assert.match(rule('table').body, /line-height:\s*1\.2\b/);
  assert.match(rule('.root button').body, /line-height:\s*inherit/);
  // the disabled look matches the review button (40 %)
  assert.match(OUTSIDE_REDUCED, /\.seg button\[aria-disabled="true"\] \{ opacity: \.4;/);
});

test('RD9: aria-controls is only present while the region it controls exists', () => {
  const closed = renderScenario('ready_diff', { ui: { detailOpen: false } }).out.cards.c7.inner;
  const open = renderScenario('ready_diff', { ui: { detailOpen: true } }).out.cards.c7.inner;
  assert.doesNotMatch(closed, /aria-controls/);
  assert.doesNotMatch(closed, /id="adv-body"/);
  assert.match(open, /aria-controls="adv-body"/);
  assert.equal(count(open, /id="adv-body"/g), 1);
});

test('RD4: card 7 is two kids (eyebrow with the toggle, keyed body) and only the body is patched in place', () => {
  for (const detailOpen of [false, true]) {
    const c7 = renderScenario('ready_diff', { ui: { detailOpen } }).out.cards.c7;
    assert.equal(c7.kids.length, 2);
    assert.match(c7.kids[0], /^<div class="eyebrow">/);
    assert.match(c7.kids[1], /^<(div id="adv-body"|p class="sentence") data-morph="adv"/);
    assert.equal(c7.kids.join(''), c7.inner);
  }
  // across a B3 publish (exp changes) the eyebrow is kept and the body is morphed, never replaced
  const a = renderScenario('ready_diff', { ui: { detailOpen: true } }).out.cards.c7.kids;
  const E = { ...scenarios.ready_diff, review: scenarios.ready_diff.review.replace('exp=112', 'exp=102') };
  const b = renderScenario('ready_diff', { E, ui: { detailOpen: true } }).out.cards.c7.kids;
  assert.deepEqual(planPatch(a, b), ['keep', 'morph']);
  // collapsing: the eyebrow carries the toggle label, so it is replaced; the body is morphed (and swaps its root)
  const closed = renderScenario('ready_diff', { ui: { detailOpen: false } }).out.cards.c7.kids;
  assert.deepEqual(planPatch(a, closed), ['replace', 'morph']);
  // both scroll regions can take focus back after a replacement
  assert.match(a[1], /<div class="scrollx" role="region" aria-label="Register values" tabindex="0" data-fk="scroll-regs">/);
  assert.match(renderScenario('ready_diff').out.cards.c6.inner, /<div class="scrollx" role="region" aria-label="Slot table" tabindex="0" data-fk="scroll-slots">/);
  const fks = [...(a.join('') + renderScenario('ready_diff').out.cards.c6.inner).matchAll(/data-fk="([^"]+)"/g)].map((m) => m[1]);
  assert.equal(new Set(fks.filter((k) => k.startsWith('scroll-'))).size, 2);
});

test('RD4: an obligation vector that changes length (six rows to the "none yet" row) is still a keyed body morph', () => {
  const six = renderScenario('ready_diff', { ui: { detailOpen: true } }).out.cards.c7.kids;
  const none = renderScenario('idle_saved', { ui: { detailOpen: true } }).out.cards.c7.kids;
  assert.deepEqual(planPatch(six, none), ['keep', 'morph']);
});

test('RD6: the card source has no second way to reach Home Assistant (no WebSocket call, REST call, message, action event, fetch, eval)', () => {
  const src = readFileSync(path.join(cardDir, 'ecco-fallback-recovery-card.js'), 'utf8');
  assert.doesNotMatch(src, /\b(callWS|callApi|callWebSocket|sendMessage|subscribeMessage|subscribeEvents|call_service)\b/);
  assert.doesNotMatch(src, /hass-action|hass-toggle-menu|navigate\b|\bfetch\b|XMLHttpRequest|WebSocket|sendBeacon|\beval\b|new Function|\bimportScripts\b/);
  assert.doesNotMatch(src, /\bhass\.(?!states|locale|config|language|callService)\w+/, 'only the five allowed hass members are named');
  assert.equal((src.match(/\bcallService\s*\(/g) || []).length, 1, 'exactly one service-call site');
  assert.equal((src.match(/dispatchEvent\(/g) || []).length, 1, 'one event dispatch (more-info)');
  assert.match(src, /new CustomEvent\('hass-more-info'/);
});

// ===========================================================================
// FB-B2: guarded Save / Invalidate rendering
// ===========================================================================
const FB2 = { FLOW_TEXT: card.FLOW_TEXT, GATE_LABEL: card.GATE_LABEL, makeFlow: card.makeFlow, saveEffect: card.saveEffect };
const keysNow = { review: 'r', b9: 'b', arm: 'a' };
/** A request this card has sent: kind 'save' | 'invalidate', state sent | running | timeout | unsure. */
const flowFor = (scenario, kind, state = 'sent') => {
  const vm = build(scenario).vm;
  const f = FB2.makeFlow(kind, { id: kind === 'save' ? vm.reviewId : vm.idHex, variant: vm.prior === 'CORRUPT' ? 'replace_corrupt' : 'save', effect: kind === 'save' ? FB2.saveEffect(vm) : null, vm, nowMs: T0, keys: keysNow });
  return { ...f, state };
};
const tagOf = (html, act) => (new RegExp(`<button[^>]*data-act="${act}"[^>]*>`).exec(html) || [null])[0];
const c4of = (name, o = {}) => renderScenario(name, o).out.cards.c4.inner;
const c1of = (name, o = {}) => renderScenario(name, o).out.cards.c1.inner;
const NOARM = Object.fromEntries(Object.entries(IDS).filter(([k]) => !['arm', 'free_power_arm', 'dump_arm', 'manual_arm'].includes(k)));
// FB-B2 (CARD-08): the confirmation panel opens only for the arm this card switched on for a save, so every render that expects the panel says so
const SAVE_UI = { intent: 'save' };

test('FB-B2 wording hygiene: every Save / Invalidate string, in every state, passes the same scan as the rest of the card', () => {
  const regexes = cardRegexes().map((r) => r.re).concat(HAZARD_PATTERNS, NEVER_WORDS);
  const texts = new Set();
  const push = (o) => {
    if (typeof o === 'string') texts.add(o);
    else if (Array.isArray(o)) o.forEach(push);
    else if (o && typeof o === 'object') Object.values(o).forEach(push);
  };
  push(FB2.FLOW_TEXT);
  push(FB2.GATE_LABEL);
  push(card.priorReplaceNote('CORRUPT'));
  // every scenario in every Save / Invalidate UI state, at a few moments
  const uis = [
    {}, { intent: 'save' }, { intent: 'invalidate' }, { intent: 'sent' }, { intent: 'save', armPending: true }, { intent: 'invalidate', armPending: true },
    { intent: 'save', cancelling: true }, { intent: 'invalidate', cancelling: true }, { notice: 'Home Assistant did not accept the request. Check the connection and try again.' },
  ];
  for (const n of names) {
    for (const ui of uis) {
      for (const [elapsedS, armOnS] of [[5, 2], [60, 20], [119, 100], [140, 2]]) {
        const { out, tv } = renderScenario(n, { elapsedS, armOnS, ui: { detailOpen: true, ...ui } });
        for (const t of allText(out, tv)) texts.add(t);
      }
    }
  }
  for (const [scenario, kind] of [['arm_on_ready', 'save'], ['arm_on_corrupt', 'save'], ['arm_on_first', 'save'], ['saving', 'save'], ['arm_on_no_candidate', 'invalidate']]) {
    for (const state of ['sent', 'running', 'timeout', 'unsure']) {
      for (const intent of ['save', 'invalidate', 'sent', null]) {
        const { out, tv } = renderScenario(scenario, { armOnS: 2, elapsedS: 10, ui: { intent, flow: flowFor(scenario, kind, state) } });
        for (const t of allText(out, tv)) texts.add(t);
      }
    }
  }
  assert.ok(texts.size > 600, `too few strings scanned: ${texts.size}`);
  for (const t of texts) {
    for (const re of regexes) assert.doesNotMatch(t, re, `"${t}" matches ${re}`);
    assert.doesNotMatch(t, /^(blocked|rejected)\b/i, `"${t}" starts with a busy-classifier word`);
  }
  for (const t of Object.values(FB2.FLOW_TEXT)) assert.ok(!/[<>]/.test(t), t);
});

test('FB-B2 candidate card: Arm Save is offered with a candidate and says why when it is not available', () => {
  // a clean candidate: the button is enabled and the caption explains the one-shot arm
  const ready = c4of('ready_match');
  const arm = tagOf(ready, 'arm');
  assert.match(arm, /type="button" class="btn" data-act="arm" data-fk="arm" aria-disabled="false"/);
  assert.doesNotMatch(arm, /\stitle=/);
  assert.match(ready, /Arm Save<\/button>/);
  assert.match(ready, /Arm turns off by itself after 2 min, and whenever you press Review, Save or Invalidate\./);
  assert.doesNotMatch(ready, /data-act="save"|class="confirm"|Save Fallback Profile/, 'no Save button before the arm is on');
  assert.match(ready, /Candidate ready for save/);
  // disabled with the reason, still focusable (aria-disabled, never the disabled attribute), reason visible AND in the title
  for (const [name, reason, extra] of [
    ['ready_other_arm_on', 'a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first (on now: Free Power)'],
    ['ready_nosup', 'Home Assistant heartbeat is not stable; wait until the dashboard shows it healthy, then review and save again'],
    ['ready_bus_busy', 'another inverter transaction is in progress; try again shortly'],
    ['arm_unavailable', 'The arm entity is unavailable'],
    ['not_saveable', 'This candidate is not saveable: see the reasons above'],
    ['not_saveable_unreadable', 'This candidate is not saveable: see the reasons above'],
  ]) {
    const html = c4of(name);
    const b = tagOf(html, 'arm');
    assert.match(b, /aria-disabled="true"/, name);
    assert.ok(b.includes(`title="${card.esc(reason)}"`), `${name}: title ${b}`);
    assert.doesNotMatch(b, /\sdisabled(\s|>|=)/, name);
    assert.ok(html.includes(`<div class="caption warnnote">${card.esc(reason)}</div>`), `${name}: visible reason`);
    assert.doesNotMatch(html, /data-act="save"/, name);
    void extra;
  }
  // no candidate, or a candidate state that is not a candidate: no Arm Save at all
  for (const n of ['idle_saved', 'reading', 'unavailable', 'expired', 'cleared', 'saved_ok']) assert.doesNotMatch(c4of(n), /data-act="arm"/, n);
  // the dashboard has no arm entity: the button is there but disabled, and says what is missing
  const noArm = c4of('ready_match', { ids: NOARM });
  assert.match(tagOf(noArm, 'arm'), /aria-disabled="true"/);
  assert.match(noArm, /Saving is not set up on this dashboard: the arm entity is missing from the card configuration\./);
  // a candidate at zero is not armed ("expiring", the firmware has not confirmed yet)
  const zero = c4of('ready_expiring', { elapsedS: 12 });
  assert.match(tagOf(zero, 'arm'), /aria-disabled="true"/);
  assert.match(zero, /The candidate is expiring: review again/);
  // the Arm press that has not been echoed yet
  const pending = c4of('ready_match', { ui: { intent: 'save', armPending: true } });
  assert.match(pending, /Arming…<\/button>/);
  assert.match(tagOf(pending, 'arm'), /aria-disabled="true"/);
  // an arm that is on but set for Invalidate: no Save panel, a strip with a way to turn it off
  const forInv = c4of('arm_on_ready', { armOnS: 2, elapsedS: 10, ui: { intent: 'invalidate' } });
  assert.doesNotMatch(forInv, /class="confirm"|data-act="save"/);
  assert.match(forInv, /The arm is set for Invalidate \(see the Saved profile card\)\. Turn it off to save instead\./);
  assert.match(tagOf(forInv, 'arm-cancel'), /data-fk="arm-cancel-strip"/);
});

test('FB-B2 confirmation panel: the candidate ID being confirmed, what the save does, every prerequisite, the arm timer, Save and Cancel', () => {
  const html = c4of('arm_on_ready', { armOnS: 3, elapsedS: 20, ui: SAVE_UI });
  assert.match(html, /<div class="confirm" role="group" aria-labelledby="confirm-save-title" data-act="stay" data-confirm="save">/);
  assert.match(html, /<div class="ctitle" id="confirm-save-title" tabindex="-1" data-fk="confirm-save-title">Confirm save<\/div>/);
  const t = textNodes(html, renderScenario('arm_on_ready', { armOnS: 3, elapsedS: 20, ui: SAVE_UI }).tv);
  const val = (k, from = 0) => t[t.indexOf(k, from) + 1];
  const at = t.indexOf('Confirm save');
  assert.ok(at > 0);
  assert.equal(val('ID being confirmed', at), '5F3A 9C21 B04E 7D18');
  assert.equal(val('What happens', at), 'Replaces the saved profile (generation 7). Expected result: generation 8.');
  assert.equal(val('Expected generation', at), '8');
  assert.equal(val('Confirmation', at), 'SAVE 5F3A9C21B04E7D18');
  assert.ok(t.includes('Arm timer: 1:43'), 'the arm countdown: 120 s from the moment Home Assistant reported the switch on');
  // every prerequisite, each with its label and state word
  assert.deepEqual([...html.matchAll(/<div class="l">([^<]*)<span class="sr"> - (passed|not met|unknown)<\/span>/g)].map((m) => [m[1], m[2]]), [
    ['Arm on', 'passed'], ['No other Fallback Profile operation running', 'passed'], ['Candidate reviewed and saveable', 'passed'],
    ['Candidate not expired', 'passed'], ['Stored profile can be replaced', 'passed'], ['Home Assistant heartbeat stable', 'passed'],
    ['Trusted time', 'passed'], ['No other write arm on', 'passed'], ['Inverter bus idle', 'passed'], ['No temporary operation active', 'passed'],
  ]);
  // the Save button carries the ID it was drawn with; Cancel turns the arm off; neither is a real `disabled` button
  const save = tagOf(html, 'save');
  assert.match(save, /class="btn go" data-act="save" data-fk="save" data-id="5F3A9C21B04E7D18" data-variant="save" aria-disabled="false"/);
  assert.doesNotMatch(save, /\stitle=|\sdisabled(\s|>)/);
  assert.match(html, /Save Fallback Profile<\/button>/);
  assert.match(tagOf(html, 'arm-cancel'), /class="btn quiet" data-act="arm-cancel" data-fk="arm-cancel"/);
  assert.match(html, /Cancel<\/button>/);
  assert.match(html, /Every attempt turns the arm off and uses up the candidate, even when it is refused\./);
  // nothing is focused for the operator, in particular not the destructive button
  assert.doesNotMatch(html, /autofocus/);
  // the time placeholders, not live text: the markup is the same at every second
  assert.equal(c4of('arm_on_ready', { armOnS: 3, elapsedS: 20, ui: SAVE_UI }), c4of('arm_on_ready', { armOnS: 3, elapsedS: 21, ui: SAVE_UI }));
  // FB-B2 (CARD-08), before: "the intent does not matter for a save panel (only invalidate hides it)". Now the panel needs the arm THIS card
  // switched on for a save: with any other intent (none, invalidate, an arm a request already used up) the arm is a strip, never a panel
  for (const intent of [undefined, null, 'invalidate', 'sent']) {
    assert.doesNotMatch(c4of('arm_on_ready', { armOnS: 3, elapsedS: 20, ui: { intent } }), /class="confirm"|data-act="save"/, String(intent));
  }
  // the panel disappears when the arm is off, while a request is pending, and while the arm is being turned off
  for (const ui of [{ intent: 'save', cancelling: true }, { intent: 'save', flow: flowFor('arm_on_ready', 'save', 'sent') }, { intent: 'save', flow: flowFor('arm_on_ready', 'invalidate', 'sent') }]) {
    assert.doesNotMatch(c4of('arm_on_ready', { armOnS: 3, elapsedS: 20, ui }), /class="confirm"|data-act="save"/, JSON.stringify(Object.keys(ui)));
  }
  assert.doesNotMatch(c4of('ready_match', { elapsedS: 20 }), /class="confirm"/);
});

test('FB-B2 confirmation panel: a failing prerequisite is named with the firmware wording and the Save button says why it is off', () => {
  const html = (patch, o = {}) => c4of('arm_on_ready', { armOnS: 3, elapsedS: 20, E: { ...scenarios.arm_on_ready, ...patch }, ...o, ui: { ...SAVE_UI, ...(o.ui || {}) } });
  for (const [patch, label, reason] of [
    [{ supervision_stable: 'off', supervision_state: 'SUSPECT' }, 'Home Assistant heartbeat stable', 'Home Assistant heartbeat is not stable; wait until the dashboard shows it healthy, then review and save again'],
    [{ ntp_synced: 'off' }, 'Trusted time', 'clock not NTP-synchronised this boot; the capture time would be untrusted'],
    [{ free_power_arm: 'on' }, 'No other write arm on', 'a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first (on now: Free Power)'],
    [{ write_lock: 'on' }, 'Inverter bus idle', 'another inverter transaction is in progress; try again shortly'],
  ]) {
    const h = html(patch);
    const save = tagOf(h, 'save');
    assert.match(save, /aria-disabled="true"/, label);
    assert.ok(save.includes(`title="${card.esc(reason)}"`), `${label}: ${save}`);
    assert.doesNotMatch(save, /\sdisabled(\s|>)/);
    assert.match(h, new RegExp(`${label.replace(/[()]/g, '\\$&')}<span class="sr"> - not met</span>`), label);
    assert.ok(h.includes(`<div class="d">${card.esc(reason)}</div>`), `${label}: item detail`);
    assert.ok(h.includes(`<div class="caption warnnote">${card.esc(reason)}</div>`), `${label}: visible reason`);
    assert.match(tagOf(h, 'arm-cancel'), /data-act="arm-cancel"/, 'Cancel stays available');
  }
  // an item the card cannot judge is "unknown" and does not stop the save
  const unknown = html({ ntp_synced: 'unavailable' });
  assert.match(unknown, /Trusted time<span class="sr"> - unknown<\/span>/);
  assert.match(tagOf(unknown, 'save'), /aria-disabled="false"/);
  // the arm expiring: no confirm any more
  const lateR = renderScenario('arm_on_ready', { armOnS: 3, elapsedS: 123, ui: SAVE_UI, E: { ...scenarios.arm_on_ready, review: scenarios.arm_on_ready.review.replace('exp=87', 'exp=120') } });
  const late = lateR.out.cards.c4.inner;
  assert.match(tagOf(late, 'save'), /aria-disabled="true"/);
  assert.match(late, /The arm is expiring - turn it off and arm again/);
  assert.ok(textNodes(late, lateR.tv).includes('Arm timer: expiring…'));
  // a notice (Home Assistant did not accept a request) is shown inside the panel as well
  assert.match(html({}, { ui: { notice: 'Home Assistant did not accept the request. Check the connection and try again.' } }), /<div class="caption warnnote">Home Assistant did not accept the request\./);
});

test('FB-B2 confirmation panel: REPLACE CORRUPT, first save and replacing a lost or stale profile say so', () => {
  const rc = c4of('arm_on_corrupt', { armOnS: 3, elapsedS: 20, ui: SAVE_UI });
  assert.match(rc, /Confirm replacing a damaged profile<\/div>/);
  assert.match(rc, /This replaces a damaged saved profile after logging its raw bytes\. It does not erase storage and does not change the inverter\./);
  assert.match(rc, /<span class="v mono phrase">SAVE C0FFEE00C0FFEE01 REPLACE CORRUPT<\/span>/);
  assert.match(tagOf(rc, 'save'), /data-id="C0FFEE00C0FFEE01" data-variant="replace_corrupt"/);
  assert.match(rc, /Replace damaged profile<\/button>/);
  assert.doesNotMatch(rc, />\s*Save Fallback Profile</);
  assert.match(rc, /Replaces a damaged stored profile\. Expected result: generation 8\./);
  const first = c4of('arm_on_first', { armOnS: 3, elapsedS: 20, ui: SAVE_UI });
  assert.match(first, /First save: no profile is stored yet\. Expected result: generation 1\./);
  assert.match(first, /<span class="v mono phrase">SAVE A1B2C3D4E5F60718<\/span>/);
  assert.match(tagOf(first, 'save'), /data-variant="save"/);
  assert.doesNotMatch(first, /REPLACE CORRUPT/);
  for (const [prior, re] of [['PROFILE_LOST', /The stored profile is missing \(last known generation 7\)\. A new one replaces it\./], ['PROFILE_STALE', /Replaces a stored profile that is out of step/]]) {
    const h = c4of('arm_on_ready', { armOnS: 3, elapsedS: 20, ui: SAVE_UI, E: { ...scenarios.arm_on_ready, review: scenarios.arm_on_ready.review.replace('prior=VALID', `prior=${prior}`) } });
    assert.match(h, re, prior);
    assert.doesNotMatch(h, /REPLACE CORRUPT confirmation\)|data-variant="replace_corrupt"/, prior);
  }
});

test('FB-B2 progress: SAVING shows a busy, announced state; the request this card sent stays on screen; no Save button exists', () => {
  const c4 = c4of('saving');
  assert.match(c4, /class="headline">SAVE IN PROGRESS</);
  assert.match(c4, /<div class="progress" role="status" aria-busy="true" tabindex="-1" data-fk="flow-status"><span class="spin" aria-hidden="true"><\/span><span>Saving - the dongle is re-reading the inverter and writing the profile record\.<\/span><\/div>/);
  assert.match(c4, /Do not press Save again\. The result appears under Last action\./);
  assert.doesNotMatch(c4, /data-act="(save|arm|arm-cancel)"|<button/);
  const sr = renderScenario('saving', { ui: { flow: { ...flowFor('arm_on_ready', 'save', 'running'), atMs: T0 } } });
  const t = textNodes(sr.out.cards.c4.inner, sr.tv);
  assert.equal(t[t.indexOf('Candidate ID') + 1], '5F3A 9C21 B04E 7D18', 'the ID of the consumed candidate stays on screen');
  assert.equal(t[t.indexOf('Expected generation') + 1], '8');
  assert.equal(t[t.indexOf('Request sent') + 1], '08:00:00');
  // the request has been sent but the dongle has not answered yet
  const sent = c4of('arm_on_ready', { armOnS: 3, elapsedS: 20, ui: { flow: flowFor('arm_on_ready', 'save', 'sent') } });
  assert.match(sent, /class="headline">SAVE REQUESTED</);
  assert.match(sent, /Request sent - waiting for the dongle\./);
  assert.match(sent, /aria-busy="true"/);
  assert.doesNotMatch(sent, /data-act="(save|arm|arm-cancel)"|class="confirm"/, 'no second submit is possible');
  // no result after the timeout: a message, and the live state decides what is offered (never an automatic retry)
  const timeout = c4of('arm_on_ready', { armOnS: 3, elapsedS: 20, ui: { flow: flowFor('arm_on_ready', 'save', 'timeout') } });
  assert.match(timeout, /<div class="warnrow">[^]*No result yet\. Check Last action before trying again; do not press Save twice\./);
  const unsure = c4of('arm_on_ready', { armOnS: 3, elapsedS: 20, ui: { flow: flowFor('arm_on_ready', 'save', 'unsure') } });
  assert.match(unsure, /Home Assistant did not accept the request, so it may not have reached the dongle\. Check Last action before trying again\./);
  // card 3: the headline, the stepper and the Review button
  const c3 = renderScenario('saving').out.cards.c3;
  assert.match(c3.inner, /class="headline">SAVING</);
  assert.match(c3.inner, /Re-reading the inverter before commit\./);
  assert.match(c3.inner, /Review progress: Saving/);
  assert.match(c3.inner, /4 reads, then the profile record is written · no inverter write/);
  assert.match(c3.inner, /<button[^>]*data-act="review"[^>]*aria-disabled="true"[^>]*title="Save in progress"/);
  assert.equal(c3.state, 'var(--busy)');
  assert.deepEqual([...c3.kids[2].matchAll(/<span>([^<]*)<\/span><\/div>/g)].map((m) => m[1]), ['Read pass 1', 'Read pass 2', 'Compare', 'Commit']);
  assert.equal(c3.kids.length, 6, 'the review card keeps its six kids');
  // while only the request is on its way, Review is held too
  const held = renderScenario('arm_on_ready', { armOnS: 3, elapsedS: 20, ui: { flow: flowFor('arm_on_ready', 'save', 'sent') } }).out.cards.c3.inner;
  assert.match(held, /aria-disabled="true"[^>]*title="Save in progress"/);
  const heldInv = renderScenario('arm_on_no_candidate', { ui: { flow: flowFor('arm_on_no_candidate', 'invalidate', 'sent') } }).out.cards.c3.inner;
  assert.match(heldInv, /aria-disabled="true"[^>]*title="Invalidate in progress"/);
  // card 2 and card 5
  assert.match(renderScenario('saving').out.cards.c2.inner, /class="headline">CHECKING</);
  assert.equal(renderScenario('saving').out.cards.c2.state, 'var(--busy)');
});

test('FB-B2 outcome panels: each result from the dongle is shown in the candidate card (save) or the saved profile card (invalidate)', () => {
  const head = (html) => /class="headline">([^<]*)</.exec(html)[1];
  for (const [name, word, tone] of [
    ['saved_ok', 'SAVED', 'var(--ok)'], ['saved_first', 'SAVED', 'var(--ok)'], ['save_refused_arm', 'SAVE REFUSED', 'var(--warn)'],
    ['save_refused_hb', 'SAVE REFUSED', 'var(--warn)'], ['save_changed', 'SAVE REFUSED', 'var(--warn)'], ['save_not_committed', 'SAVE NOT COMMITTED', 'var(--bad)'],
    ['save_stale_witness', 'SAVE NOT COMMITTED', 'var(--bad)'], ['save_unknown', 'SAVE OUTCOME UNKNOWN', 'var(--bad)'], ['action_refused', 'REFUSED', 'var(--warn)'],
  ]) {
    const { out } = renderScenario(name);
    assert.equal(head(out.cards.c4.inner), word, name);
    assert.equal(out.cards.c4.state, tone, name);
    assert.doesNotMatch(out.cards.c4.inner, /data-act="(arm|save)"/, `${name}: terminal until the next review`);
  }
  // an invalidate result is not a candidate-card state
  for (const n of ['invalidated_ok', 'invalidate_refused', 'invalidate_stale', 'invalidate_unknown']) {
    assert.equal(head(c4of(n)), 'NO CANDIDATE', n);
  }
  // verified saved: B1 VALID + B9 SAVED + the same generation in B2, with the date from B2 `at`
  const ok = textNodes(c4of('saved_ok'));
  assert.equal(ok[1], 'SAVED');
  assert.equal(ok[2], 'Saved and verified this boot: generation 8, 12 Sept 2026, 14:23.');
  assert.deepEqual(ok.slice(3), ['Generation', '8', 'Saved', '12 Sept 2026, 14:23', 'ID', '7C5A0E91']);
  assert.match(c1of('saved_ok'), /Known-good profile generation 8, saved 12 Sept 2026, 14:23\./);
  // the first save
  assert.match(textNodes(c4of('saved_first')).join(' '), /Saved and verified this boot: generation 1, /);
  // SAVE_UNCONFIRMED: B1 is unusable and says restart; the outcome says do not press Save again and when not to restart
  const unk = renderScenario('save_unknown').out;
  assert.match(unk.cards.c1.inner, /The last save could not be confirmed\. Restart the dongle when no temporary operation is active; saving stays disabled until then\./);
  assert.match(unk.cards.c4.inner, /Do not press Save again\. If a temporary operation \(Free Power, Dump to Grid, register 244 test\) is active or needs a decision, do not restart the dongle\./);
  assert.match(unk.cards.c3.inner, /Last action: <b>SAVE OUTCOME UNKNOWN - storage reported E105\/READ_ERROR; reboot the dongle \(when no temporary operation is active\) to re-verify; saving disabled until then<\/b>/);
  assert.match(unk.cards.c3.inner, /--tone:var\(--bad\)/);
  assert.doesNotMatch(unk.cards.c1.inner, /data-act="arm-invalidate"/, 'an unconfirmed profile cannot be invalidated');
  // invalidate outcomes in card 1
  for (const [name, word] of [['invalidated_ok', 'INVALIDATED'], ['invalidate_refused', 'INVALIDATE REFUSED'], ['invalidate_stale', 'INVALIDATE NOT COMMITTED'], ['invalidate_unknown', 'INVALIDATE OUTCOME UNKNOWN']]) {
    const c1 = c1of(name);
    // FB-B2 (CARD-12): the result heading carries tabindex -1 and a focus key, so the outcome that replaces the progress row can take focus
    assert.match(c1, new RegExp(`<div class="actres (ok|warn|bad)" data-act="stay"><div class="at" tabindex="-1" data-fk="act-result-inv">${word}</div>`), name);
  }
  assert.match(c1of('invalidated_ok'), /Invalidated: the profile can no longer be used\. Save a new profile to re-enable it\./);
  // after a refused invalidate the profile is still VALID: the control is there again
  assert.match(tagOf(c1of('invalidate_refused'), 'arm-invalidate'), /aria-disabled="false"/);
  assert.doesNotMatch(c1of('invalidated_ok'), /data-act="arm-invalidate"/);
});

test('FB-B2 Saved profile card: the guarded Invalidate control, only for a VALID profile and only with an arm entity', () => {
  const idle = c1of('idle_saved');
  const arm = tagOf(idle, 'arm-invalidate');
  assert.match(arm, /type="button" class="btn quiet" data-act="arm-invalidate" data-fk="arm-invalidate" aria-disabled="false"/);
  assert.match(idle, /Arm Invalidate<\/button>/);
  assert.match(idle, /Arm turns off by itself after 2 min, and whenever you press Review, Save or Invalidate\./);
  assert.match(idle, /<div class="actblock" data-act="stay">/, 'a click on the control block never opens the more-info dialog');
  // no other class, no unavailable profile, no arm entity: no control
  for (const n of ['not_captured', 'invalidated', 'unusable', 'unreadable', 'profile_lost', 'profile_stale', 'corrupt_domain', 'save_unconfirmed', 'unavailable']) {
    assert.doesNotMatch(c1of(n), /data-act="arm-invalidate"|Arm Invalidate/, n);
  }
  assert.doesNotMatch(c1of('idle_saved', { ids: NOARM }), /Arm Invalidate|data-act="arm-invalidate"/);
  // VALID with a lagging witness can still be invalidated
  assert.match(tagOf(c1of('witness_lag'), 'arm-invalidate'), /aria-disabled="false"/);
  // reasons it cannot be armed now
  for (const [patch, reason] of [
    [{ write_lock: 'on' }, 'another inverter transaction is in progress; try again shortly'],
    [{ arm: 'unavailable' }, 'The arm entity is unavailable'],
    [{ review: scenarios.reading.review, last_result: scenarios.reading.last_result }, 'another Fallback Profile operation is in progress'],
    [{ saved_slots: scenarios.idle_saved.saved_slots.replace('b=2BAEBFE9', 'b=00000000') }, 'The saved values on screen do not match the stored profile ID; wait for the dashboard to update'],
  ]) {
    const h = c1of('idle_saved', { E: { ...scenarios.idle_saved, ...patch } });
    assert.match(tagOf(h, 'arm-invalidate'), /aria-disabled="true"/, reason);
    assert.ok(h.includes(`title="${card.esc(reason)}"`), reason);
    assert.ok(h.includes(`<div class="caption warnnote">${card.esc(reason)}</div>`), reason);
  }
  // supervision, time and the other write arms are NOT prerequisites of an invalidate
  assert.match(tagOf(c1of('idle_saved', { E: { ...scenarios.idle_saved, supervision_stable: 'off', supervision_state: 'LOST', ntp_synced: 'off', free_power_arm: 'on' } }), 'arm-invalidate'), /aria-disabled="false"/);
  // the arm press that has not been echoed yet
  assert.match(c1of('idle_saved', { ui: { intent: 'invalidate', armPending: true } }), /Arming…<\/button>/);
  assert.match(c1of('idle_saved', { ui: { intent: 'save', armPending: true } }), /Arm Invalidate<\/button>/, 'a pending save arm does not relabel the invalidate button');
});

test('FB-B2 invalidate confirmation: the stored profile\'s full 16-hex binding, the phrase, every prerequisite, the candidate note', () => {
  const o = { armOnS: 2, elapsedS: 10, ui: { intent: 'invalidate' } };
  const html = c1of('arm_on_no_candidate', o);
  assert.match(html, /<div class="confirm inv" role="group" aria-labelledby="confirm-inv-title" data-act="stay" data-confirm="invalidate">/);
  assert.match(html, /<div class="ctitle" id="confirm-inv-title" tabindex="-1" data-fk="confirm-inv-title">Confirm invalidate<\/div>/);
  assert.match(html, /This makes the saved profile unusable\. It is kept for reference but will never be used until you save a new one\. The inverter is not changed\./);
  const t = textNodes(html, renderScenario('arm_on_no_candidate', o).tv);
  const at = t.indexOf('Confirm invalidate');
  assert.equal(t[t.indexOf('ID being confirmed', at) + 1], '2BAE BFE9 7F4E 04BC', 'the FULL binding, grouped, not the 8-hex short ID');
  assert.equal(t[t.indexOf('Confirmation', at) + 1], 'INVALIDATE 2BAEBFE97F4E04BC');
  assert.ok(t.includes('Arm timer: 1:52'));
  assert.deepEqual([...html.matchAll(/<div class="l">([^<]*)<span class="sr"> - (passed|not met|unknown)<\/span>/g)].map((m) => m[1]),
    ['Arm on', 'No other Fallback Profile operation running', 'Saved profile is VALID', 'Generation can advance', 'Profile ID matches the saved values', 'Inverter bus idle']);
  assert.match(tagOf(html, 'invalidate'), /class="btn go" data-act="invalidate" data-fk="invalidate" data-id="2BAEBFE97F4E04BC" aria-disabled="false"/);
  assert.match(html, /Invalidate Profile<\/button>/);
  assert.match(tagOf(html, 'arm-cancel'), /data-fk="arm-cancel-inv"/);
  assert.match(html, /Every attempt turns the arm off, even when it is refused\./);
  assert.doesNotMatch(html, /This also discards the current candidate/);
  // with a candidate pending the panel says it is discarded
  const withCand = c1of('arm_on_ready', o);
  assert.match(withCand, /This also discards the current candidate\./);
  // the invalidate panel needs the invalidate intent: a save arm shows the Arm button, not this panel
  assert.doesNotMatch(c1of('arm_on_no_candidate', { armOnS: 2, elapsedS: 10, ui: { intent: 'save' } }), /class="confirm inv"/);
  assert.doesNotMatch(c1of('arm_on_no_candidate', { armOnS: 2, elapsedS: 10 }), /class="confirm inv"/, 'no intent (an arm set elsewhere, or after a reload): turn it off and choose');
  assert.doesNotMatch(c1of('arm_on_no_candidate', { ...o, ui: { intent: 'invalidate', cancelling: true } }), /class="confirm inv"/);
  // a failing prerequisite switches the button off and says why
  const busy = c1of('arm_on_no_candidate', { ...o, E: { ...scenarios.arm_on_no_candidate, write_lock: 'on' } });
  assert.match(tagOf(busy, 'invalidate'), /aria-disabled="true"[^>]*title="another inverter transaction is in progress; try again shortly"/);
  assert.match(busy, /Inverter bus idle<span class="sr"> - not met<\/span>/);
  // the strip in the candidate card tells a stray arm how to be turned off
  const strip = c4of('arm_on_no_candidate', { armOnS: 2, elapsedS: 10 });
  assert.match(strip, /<div class="armstrip" data-act="stay">/);
  // FB-B2 (CARD-08), before: "Arm is on." for an arm with no intent. An arm no click of this card switched on says so; "Arm is on." is for this
  // card's own save arm that has no candidate to confirm; a spent arm and an invalidate arm have their own words
  assert.match(strip, /Arm was turned on elsewhere\. Arm timer: <span data-t="arm"><\/span>/);
  assert.doesNotMatch(strip, /Arm is on\./);
  assert.match(c4of('arm_on_no_candidate', { armOnS: 2, elapsedS: 10, ui: SAVE_UI }), /Arm is on\. Arm timer: <span data-t="arm"><\/span>/);
  assert.match(c4of('arm_on_no_candidate', { armOnS: 2, elapsedS: 10, ui: { intent: 'sent' } }), /This arm was already used by your request\. Arm timer: <span data-t="arm"><\/span>/);
  assert.match(tagOf(strip, 'arm-cancel'), /data-fk="arm-cancel-strip"/);
  assert.match(strip, /Turn arm off<\/button>/);
  assert.doesNotMatch(c4of('idle_saved'), /armstrip/);
});

test('FB-B2 Invalidate request: sent state and the unanswered message show in the Saved profile card', () => {
  const sent = c1of('arm_on_no_candidate', { ui: { intent: 'invalidate', flow: flowFor('arm_on_no_candidate', 'invalidate', 'sent') } });
  assert.match(sent, /Invalidate request sent - waiting for the dongle\./);
  assert.match(sent, /aria-busy="true"/);
  assert.doesNotMatch(sent, /data-act="(invalidate|arm-invalidate|arm-cancel)"|class="confirm/);
  const t = textNodes(sent);
  assert.equal(t[t.indexOf('Profile ID') + 1], '2BAE BFE9 7F4E 04BC');
  const timeout = c1of('idle_saved', { ui: { flow: flowFor('idle_saved', 'invalidate', 'timeout') } });
  assert.match(timeout, /No result yet\. Check Last action before trying again; do not press Invalidate twice\./);
  assert.match(tagOf(timeout, 'arm-invalidate'), /aria-disabled="false"/, 'a timed-out request does not hold the control for ever');
});

test('FB-B2 accessibility and structure: write buttons carry data-act and a focus key, none uses the disabled attribute, panels are named groups', () => {
  const states = [
    ['ready_match', {}], ['ready_other_arm_on', {}], ['not_saveable', {}], ['arm_on_ready', { armOnS: 3, elapsedS: 20, ui: SAVE_UI }], ['arm_on_corrupt', { armOnS: 3, elapsedS: 20, ui: SAVE_UI }],
    ['arm_on_no_candidate', { armOnS: 2, elapsedS: 10, ui: { intent: 'invalidate' } }], ['idle_saved', {}], ['saving', {}],
  ];
  for (const [n, o] of states) {
    const { out } = renderScenario(n, o);
    const all = html(out);
    for (const m of all.matchAll(/<button[^>]*>/g)) {
      assert.doesNotMatch(m[0], /\sdisabled(\s|>|=)/, `${n}: ${m[0]}`);
      assert.match(m[0], /data-fk="[^"]+"|data-act="[^"]+"/, `${n}: every button is reachable by a key or an action`);
    }
    for (const m of all.matchAll(/<button[^>]*data-act="(arm|arm-invalidate|arm-cancel|save|invalidate)"[^>]*>/g)) {
      assert.match(m[0], /data-fk="[^"]+"/, `${n}: ${m[1]} has a focus key (focus is restored after a re-render)`);
      assert.match(m[0], /type="button"/);
    }
    for (const m of all.matchAll(/class="confirm[^"]*" role="group" aria-labelledby="([^"]+)"/g)) {
      assert.match(all, new RegExp(`id="${m[1]}" tabindex="-1"`), `${n}: the panel is named by its heading, which can take focus`);
    }
    assert.equal(count(all, /aria-live/g), count(out.cards.c3.inner, /aria-live/g), `${n}: the only live regions are the review card's`);
  }
  // every id and focus key is unique inside a render (a duplicate id would break aria-labelledby)
  const { out } = renderScenario('arm_on_ready', { armOnS: 3, elapsedS: 20, ui: SAVE_UI });
  const ids = [...html(out).matchAll(/\sid="([^"]+)"/g)].map((m) => m[1]);
  assert.equal(new Set(ids).size, ids.length, ids.join(','));
});

test('FB-B2 CSS: the new controls keep the 44 px target, wrap long phrases, and the spinner stops under reduced motion', () => {
  const rule = (sel) => rulesOf(OUTSIDE_REDUCED).find((r) => r.selectors.includes(sel));
  for (const sel of ['.confirm', '.ctitle', '.phrase', '.armcount', '.armstrip', '.actblock', '.actres', '.progress', '.spin', '.btn.go', '.btn.quiet']) assert.ok(rule(sel), `${sel} is styled`);
  assert.match(rule('.btn').body, /min-height:\s*44px/, '.btn.go and .btn.quiet inherit the 44 px height');
  assert.match(rule('.phrase').body, /overflow-wrap:\s*anywhere/);
  assert.match(rule('.spin').body, /animation:\s*spin/);
  assert.match(OUTSIDE_REDUCED, /@keyframes spin \{ to \{ transform: rotate\(360deg\); \} \}/);
  assert.match(REDUCED.body, /\.rail-busy \.step\.on::before, \.spin \{ animation: none !important; \}/);
  // the confirm and result blocks are not clickable looking inside a tappable card
  assert.match(rule('.confirm').body, /cursor:\s*default/);
  assert.match(rule('.actres').body, /cursor:\s*default/);
  // dark tokens only: no light-theme or viewport rule was added for the new blocks
  assert.doesNotMatch(STYLE, /@media \(max-width|prefers-color-scheme/);
  // the Recovery area keeps three ghost tiles in a three-column grid
  assert.match(rule('.ghosts').body, /repeat\(3, minmax\(0, 1fr\)\)/);
});

test('FB-B2 source guards: the arm and execute calls are built in exactly the click handlers; trusted clicks only', () => {
  const src = readFileSync(path.join(cardDir, 'ecco-fallback-recovery-card.js'), 'utf8').replace(/\r\n/g, '\n');
  // which class method builds which service call
  const builds = [];
  let method = null;
  for (const line of src.split('\n')) {
    const m = /^  (?:async )?(_?\w+)\(.*\) \{$/.exec(line);
    if (m) method = m[1];
    const b = /buildServiceCall\(([^,)]+)/.exec(line);
    if (b && method) builds.push(`${method}:${b[1].replace(/'/g, '')}`);
  }
  assert.deepEqual(builds.sort(), ['_cancelArm:arm_off', '_pressArm:arm_on', '_pressInvalidate:invalidate', '_pressReview:review', '_pressSave:kind', '_toggleDetail:detail_toggle'].sort());
  // the five guarded actions go through the trusted-click guard, and the guard reads event.isTrusted
  for (const act of ['arm', 'arm-invalidate', 'arm-cancel', 'save', 'invalidate']) {
    assert.match(src, new RegExp(`case '${act}':\\n\\s+return this\\._trusted\\(ds, `), act);
  }
  // FB-B2 (CARD-09), before: `trusted: !!e && e.isTrusted === true` (a flag in the arguments of the public _act) and `ds.trusted !== true`. Now the
  // listener closure alone decides: it hands the module-private CLICK_PASS to _onClick for an isTrusted event only, and the guard checks that pass
  assert.match(src, /this\._root\.addEventListener\('click', \(e\) => this\._onClick\(e, e && e\.isTrusted === true \? CLICK_PASS : null\)\);/);
  assert.match(src, /if \(ds\.pass !== CLICK_PASS\) return \{ sent: false, why: FLOW_TEXT\.notAUserClick \};/);
  assert.equal((src.match(/CLICK_PASS/g) || []).length, 4, 'the pass is declared once, handed out once (the listener), checked once, and named once in a comment');
  assert.doesNotMatch(src, /export const CLICK_PASS|export \{[^}]*CLICK_PASS/, 'the pass is not exported');
  assert.doesNotMatch(src, /this\.\w*[pP]ass\b/, 'the pass is not stored on the element');
  // the ID that goes out is the on-screen one, compared before anything is sent
  assert.match(src, /if \(ds\.id !== vm\.reviewId \|\| \(ds\.variant \|\| 'save'\) !== gate\.variant\)/);
  assert.match(src, /if \(ds\.id !== vm\.idHex\)/);
  // no timer, interval or render function reaches the guarded actions
  for (const fn of ['_tick', '_renderCards', '_update', '_ensureTimer', '_visibilityChanged', '_apply', '_patchCard']) {
    const body = new RegExp(`\\n  ${fn}\\([^)]*\\) \\{\\n([\\s\\S]*?)\\n  \\}\\n`).exec(src);
    assert.ok(body, fn);
    assert.doesNotMatch(body[1], /_pressArm|_pressSave|_pressInvalidate|_cancelArm|_act\(|_call\(|buildServiceCall/, `${fn} never acts`);
  }
});

test('FB-B2 confirmation panel: "Stored now" names what is stored (class, generation, saved time from B2) for every kind of prior', () => {
  const stored = (name, patch = {}) => {
    const r = renderScenario(name, { armOnS: 3, elapsedS: 20, ui: SAVE_UI, E: { ...scenarios[name], ...patch } });
    const t = textNodes(r.out.cards.c4.inner, r.tv);
    const at = t.indexOf('Confirm save') >= 0 ? t.indexOf('Confirm save') : t.indexOf('Confirm replacing a damaged profile');
    return t[t.indexOf('Stored now', at) + 1];
  };
  assert.equal(stored('arm_on_ready'), 'VALID profile, generation 7, saved 12 Sept 2026, 14:15');
  assert.equal(stored('arm_on_first'), 'Nothing is stored yet');
  assert.equal(stored('arm_on_corrupt'), 'A damaged profile that cannot be read');
  assert.equal(stored('arm_on_ready', { review: scenarios.arm_on_ready.review.replace('prior=VALID', 'prior=PROFILE_LOST') }), 'The profile is missing (last known generation 7)');
  assert.equal(stored('arm_on_ready', { review: scenarios.arm_on_ready.review.replace('prior=VALID', 'prior=INVALIDATED') }), 'INVALIDATED profile, generation 7, saved 12 Sept 2026, 14:15');
  assert.equal(stored('arm_on_ready', { summary: scenarios.arm_on_ready.summary.replace('at=1789222500', 'at=0') }), 'VALID profile, generation 7, capture time unknown');
  assert.equal(card.storedNowText(build('arm_on_ready').vm, fmt), 'VALID profile, generation 7, saved 12 Sept 2026, 14:15');
});

test('FB-B2 hostile text in a Save / Invalidate outcome never becomes markup, and an outcome with absurd numbers renders as text', () => {
  const evil = '<img src=x onerror=alert(1)><script>alert(2)</script>"\'&';
  for (const prefix of ['SAVED - known-good profile generation 99999999999 saved', 'SAVE REFUSED -', 'SAVE NOT COMMITTED -', 'SAVE OUTCOME UNKNOWN -', 'INVALIDATED - profile generation 4294967295 is no longer usable (now INVALIDATED g4294967296);',
    'INVALIDATE REFUSED -', 'INVALIDATE NOT COMMITTED -', 'INVALIDATE OUTCOME UNKNOWN -', "REFUSED - unsupported action '<b>'"]) {
    for (const base of ['idle_saved', 'invalidated_ok', 'save_unknown']) {
      const E = { ...scenarios[base], last_result: `${prefix} ${evil}` };
      const { out, tv } = renderScenario(base, { E, ui: { detailOpen: true } });
      const markup = fillTime(out.header + html(out), tv);
      assert.doesNotMatch(markup, /<img|<script/i, `${prefix} / ${base}`);
      assert.ok(!markup.includes("action '<b>'"), `${prefix} / ${base}: the payload tag is escaped`);
      assert.doesNotMatch(markup, /<[^>]*\son[a-z]+\s*=/i, `${prefix} / ${base}`);
      assert.doesNotMatch(markup, /undefined|NaN|\[object/, `${prefix} / ${base}`);
    }
  }
  // an arm entity or a request ID that is not what it should be never reaches an attribute
  const hostileArm = renderScenario('arm_on_ready', { E: { ...scenarios.arm_on_ready, arm: '"><img src=x>' } });
  assert.doesNotMatch(html(hostileArm.out), /<img/);
  const hostileId = renderScenario('arm_on_ready', { armOnS: 3, E: { ...scenarios.arm_on_ready, review_id: '"><img src=x onerror=alert(1)>' } });
  assert.doesNotMatch(html(hostileId.out), /<img/);
  const saveTag = /<button[^>]*data-act="save"[^>]*>/.exec(hostileId.out.cards.c4.inner);
  assert.ok(!saveTag || (/aria-disabled="true"/.test(saveTag[0]) && /data-id=""/.test(saveTag[0])), 'a malformed ID is never confirmed: the button is off and carries no ID');
});

// ===========================================================================
// FB-B2 card-fix: the findings of the independent safety audit (CARD-01, 02, 03, 07, 08, 12)
// ===========================================================================
/** Every element of an HTML string, parsed (a payload that broke out of an attribute shows up here as an element or an on* attribute). */
const elementsOf = (markup) => {
  const out = [];
  const walk = (n) => {
    if (n.nodeType === 1) {
      out.push(n);
      n.childNodes.forEach(walk);
    }
  };
  parseHtml(markup, new MDocument()).forEach(walk);
  return out;
};
const assertNoInjection = (markup, label) => {
  assert.doesNotMatch(markup, /<img|<script|<iframe/i, `${label}: no raw tag from entity text`);
  const bad = elementsOf(markup).filter((e) => ['IMG', 'SCRIPT', 'IFRAME', 'OBJECT'].includes(e.nodeName) || [...e.attrs.keys()].some((k) => /^on/i.test(k)));
  assert.deepEqual(bad.map((e) => e.nodeName), [], `${label}: no injected element or event-handler attribute`);
};

test('FB-B2 CARD-02: entity text that reaches a gate reason (the supervision state) is escaped in every place a reason is printed', () => {
  const payloads = [
    '<img src=x onerror=alert(1)>',
    '"><img src=x onerror=alert(1)>',
    '" onmouseover="alert(1)',
    "' onmouseover='alert(1)",
    '"><script>alert(2)</script>',
    '<iframe src=//x></iframe>',
  ];
  let places = 0;
  for (const payload of payloads) {
    for (const stable of ['on', 'unavailable', 'unknown', 'off']) {
      const state = { supervision_stable: stable, supervision_state: payload };
      // confirmation panel (reason list, Save title, visible reason) with the arm on for this card's save
      const open = renderScenario('arm_on_ready', { armOnS: 3, elapsedS: 20, ui: SAVE_UI, E: { ...scenarios.arm_on_ready, ...state } });
      // Arm Save (title, visible reason) with the arm off, and cards 1 and 5
      const closed = renderScenario('ready_match', { E: { ...scenarios.ready_match, ...state } });
      const label = `${payload} / stable ${stable}`;
      for (const [where, r] of [['confirm', open], ['armed', closed]]) {
        for (const id of ['c1', 'c4', 'c5']) {
          assertNoInjection(fillTime(r.out.cards[id].inner, r.tv), `${label} / ${where} / ${id}`);
          places += 1;
        }
      }
      // the payload really is printed (as text) where the state is named: a vacuous pass would hide a removed esc()
      if (stable !== 'off') {
        for (const r of [open, closed]) {
          assert.ok(fillTime(r.out.cards.c5.inner, r.tv).includes(card.esc(payload)), `${label}: check 5 names the state, escaped`);
        }
        const confirmHtml = fillTime(open.out.cards.c4.inner, open.tv);
        assert.ok(confirmHtml.includes(`<div class="d">Supervision state is ${card.esc(payload)}, not SUPERVISED</div>`), `${label}: the gate item names the state, escaped`);
        assert.ok(confirmHtml.includes(`title="Supervision state is ${card.esc(payload)}, not SUPERVISED"`), `${label}: the Save button title is escaped`);
        assert.ok(confirmHtml.includes(`<div class="caption warnnote">Supervision state is ${card.esc(payload)}, not SUPERVISED</div>`), `${label}: the visible reason is escaped`);
        const armedHtml = fillTime(closed.out.cards.c4.inner, closed.tv);
        assert.ok(armedHtml.includes(`title="Supervision state is ${card.esc(payload)}, not SUPERVISED"`), `${label}: the Arm Save title is escaped`);
        assert.ok(armedHtml.includes(`<div class="caption warnnote">Supervision state is ${card.esc(payload)}, not SUPERVISED</div>`), `${label}: the Arm Save reason is escaped`);
      }
    }
  }
  assert.equal(places, payloads.length * 4 * 2 * 3);
  // the other entity-reachable reasons: the B9 text and the stored-profile class never reach an attribute or a tag unescaped either
  for (const payload of payloads) {
    const E = { ...scenarios.arm_on_ready, last_result: `SAVE REFUSED - ${payload}`, profile_state: payload };
    const r = renderScenario('arm_on_ready', { armOnS: 3, elapsedS: 20, ui: SAVE_UI, E });
    for (const id of Object.keys(r.out.cards)) assertNoInjection(fillTime(r.out.cards[id].inner, r.tv), `${payload} / B9 + B1 / ${id}`);
  }
});

test('FB-B2 CARD-01: card 5, its footer and the candidate card agree when the stable entity is unavailable and the state is not SUPERVISED', () => {
  const E = { ...scenarios.ready_match, supervision_stable: 'unavailable', supervision_state: 'LOST' };
  const r = renderScenario('ready_match', { E });
  assert.match(r.out.cards.c5.inner, /Supervision state is LOST, not SUPERVISED/);
  assert.doesNotMatch(r.out.cards.c5.inner, /Entity unavailable<\/div><\/div><\/div><div class="check (pass|unknown)">[^]*Trusted time/, 'check 5 is not "unknown"');
  assert.match(r.out.cards.c5.inner, /<div class="foot bad">Save would be refused: Supervision stable\.<\/div>/);
  assert.equal(r.out.cards.c5.state, 'var(--bad)');
  const arm = tagOf(r.out.cards.c4.inner, 'arm');
  assert.match(arm, /aria-disabled="true"/);
  assert.ok(arm.includes('title="Supervision state is LOST, not SUPERVISED"'), arm);
  assert.ok(r.out.cards.c4.inner.includes('<div class="caption warnnote">Supervision state is LOST, not SUPERVISED</div>'));
  assert.doesNotMatch(r.out.cards.c4.inner, /not shown on this dashboard/);
  // with the arm on for this card's save the panel names it and the Save button is off
  const open = renderScenario('arm_on_ready', { armOnS: 3, elapsedS: 20, ui: SAVE_UI, E: { ...scenarios.arm_on_ready, supervision_stable: 'unavailable', supervision_state: 'LOST' } });
  assert.match(tagOf(open.out.cards.c4.inner, 'save'), /aria-disabled="true"/);
  assert.match(open.out.cards.c4.inner, /Home Assistant heartbeat stable<span class="sr"> - not met<\/span>/);
  // what the card cannot judge at all is still "unknown" and still offers the save
  const unknown = renderScenario('ready_match', { E: { ...scenarios.ready_match, supervision_stable: 'unavailable', supervision_state: 'unavailable' } });
  assert.match(unknown.out.cards.c5.inner, /Entity unavailable/);
  assert.match(tagOf(unknown.out.cards.c4.inner, 'arm'), /aria-disabled="false"/);
});

test('FB-B2 CARD-03: no rendered text claims a save or an invalidate as done unless B9 says so and the card verified it', () => {
  // the completion claims: a verified save / invalidate outcome is the only place any of them may appear
  const CLAIMS = [
    /\bSaved and verified\b/i,
    /^Invalidated:/,
    /\b(profile|configuration|values?|it|this|that) (was|has been|is now|were|have been) (saved|invalidated)\b/i,
    /\b(save|invalidate)d? (succeeded|completed?|done|successful(ly)?)\b/i,
    /\bsuccess(ful(ly)?)?\b/i,
    /\bnow (saved|invalidated)\b/i,
  ];
  // B1 INVALIDATED is a state of the stored profile, not a claim about a request of this card
  const STATE_SENTENCES = new Set([SENTENCE.invalidated]);
  const uis = [{}, { intent: 'save' }, { intent: 'invalidate' }, { intent: 'sent' }, { intent: 'save', armPending: true }];
  const flows = [null, 'sent', 'running', 'timeout', 'unsure'];
  let scanned = 0;
  let claimsSeen = 0;
  for (const n of names) {
    const vm0 = build(n).vm;
    const act = vm0.act;
    const savedDone = !!act && act.family === 'save' && act.outcome === 'saved';
    const invDone = !!act && act.family === 'invalidate' && act.outcome === 'invalidated';
    // the dongle's own B9 words, echoed verbatim (Last action, the outcome detail, the raw strings), are its report and not a claim of the card
    const verbatim = new Set([vm0.b9.raw, vm0.b9.detail].filter(Boolean));
    for (const ui of uis) {
      for (const flow of flows) {
        const f = flow ? flowFor(n, vm0.hasCand || vm0.review === 'saving' ? 'save' : 'invalidate', flow) : null;
        const { out, tv } = renderScenario(n, { elapsedS: 20, armOnS: 3, ui: { detailOpen: true, ...ui, flow: f } });
        const texts = allText(out, tv);
        scanned += texts.length;
        for (const t of texts) {
          for (const re of CLAIMS) {
            if (!re.test(t) || STATE_SENTENCES.has(t) || verbatim.has(t)) continue;
            claimsSeen += 1;
            const allowed = (re === CLAIMS[0] && savedDone && act.verified) || (re === CLAIMS[1] && invDone && act.verified);
            assert.ok(allowed, `${n} / ${JSON.stringify(Object.keys(ui))} / flow ${flow}: "${t}" claims a completion (${re}) outside a verified B9 outcome`);
          }
        }
        // the outcome headline words: SAVED only in the candidate card for a B9 SAVED; INVALIDATED as a result only for a B9 INVALIDATED
        const head4 = /class="headline">([^<]*)</.exec(out.cards.c4.inner)[1];
        if (head4 === 'SAVED') assert.ok(savedDone, `${n}: the candidate card says SAVED only for a B9 SAVED outcome`);
        if (/class="at"[^>]*>INVALIDATED</.test(out.cards.c1.inner)) assert.ok(invDone, `${n}: the result block says INVALIDATED only for a B9 INVALIDATED outcome`);
      }
    }
  }
  assert.ok(scanned > 5000, `scanned ${scanned} texts`);
  assert.ok(claimsSeen >= 4, `the scan saw the verified outcomes it allows (${claimsSeen}): it is not vacuous`);
  // unverified B9 SAVED / INVALIDATED outcomes use the "waiting" wording and never the "done" wording
  for (const [n, patch] of [['saved_ok', { summary: scenarios.saved_ok.summary.replace('w=OK', 'w=LAG') }], ['saved_ok', { summary: scenarios.idle_saved.summary }], ['invalidated_ok', { summary: scenarios.invalidated_ok.summary.replace('op=INV', 'op=SAVE') }]]) {
    const { out, tv } = renderScenario(n, { E: { ...scenarios[n], ...patch } });
    const all = allText(out, tv);
    assert.ok(all.some((t) => /^The dongle reports the (save|invalidation)\. Waiting for the saved profile to update\.$/.test(t)), n);
    for (const t of all) for (const re of [CLAIMS[0], CLAIMS[1]]) assert.doesNotMatch(t, re, `${n}: ${t}`);
  }
});

test('FB-B2 CARD-08: an arm that is on without an Arm click of this card shows the strip, never the confirmation, for every intent', () => {
  const STRIP = { null: 'Arm was turned on elsewhere.', save: 'Arm is on.', invalidate: 'The arm is set for Invalidate (see the Saved profile card). Turn it off to save instead.', sent: 'This arm was already used by your request.' };
  for (const name of ['arm_on_ready', 'arm_on_corrupt', 'arm_on_first', 'arm_on_no_candidate']) {
    for (const intent of [null, 'invalidate', 'sent', 'save']) {
      const ui = { intent };
      const html = c4of(name, { armOnS: 3, elapsedS: 20, ui });
      const hasCandidate = name !== 'arm_on_no_candidate';
      const label = `${name} / intent ${intent}`;
      if (hasCandidate && intent === 'save') {
        assert.match(html, /class="confirm"/, label);
        assert.doesNotMatch(html, /class="armstrip"/, label);
        continue;
      }
      assert.doesNotMatch(html, /class="confirm"|data-act="save"|Save Fallback Profile|Replace damaged profile/, `${label}: no confirmation, no Save button`);
      assert.match(html, /<div class="armstrip" data-act="stay">/, label);
      assert.ok(html.includes(`${STRIP[intent]} Arm timer: <span data-t="arm"></span>`), `${label}: ${STRIP[intent]}`);
      assert.match(tagOf(html, 'arm-cancel'), /data-fk="arm-cancel-strip"/, `${label}: a way to turn the arm off`);
      assert.match(html, /Turn arm off<\/button>/, label);
      if (hasCandidate) assert.match(tagOf(html, 'arm'), /aria-disabled="true"[^>]*title="The arm is already on"/, `${label}: Arm Save is not offered while the arm is on`);
    }
  }
  // the saved profile card: an arm on without an Invalidate click of this card has no confirmation either
  for (const intent of [null, 'save', 'sent']) {
    const html = c1of('arm_on_no_candidate', { armOnS: 2, elapsedS: 10, ui: { intent } });
    assert.doesNotMatch(html, /class="confirm inv"|data-act="invalidate"/, String(intent));
    assert.match(tagOf(html, 'arm-invalidate'), /aria-disabled="true"/, String(intent));
  }
  assert.match(c1of('arm_on_no_candidate', { armOnS: 2, elapsedS: 10, ui: { intent: 'invalidate' } }), /class="confirm inv"/);
});

test('FB-B2 CARD-07: a candidate whose values are not on screen, or a missing saved-profile summary, cannot be armed or saved, and no generation is invented', () => {
  const noValues = { ...scenarios.ready_match, review_slots: 'unavailable', review_context: 'unavailable' };
  const closed = renderScenario('ready_match', { E: noValues });
  assert.match(tagOf(closed.out.cards.c4.inner, 'arm'), /aria-disabled="true"/);
  assert.ok(closed.out.cards.c4.inner.includes(`<div class="caption warnnote">${card.esc(card.FLOW_TEXT.candValuesMissing)}</div>`));
  assert.match(closed.out.cards.c5.inner, /<div class="foot warn">Save is not ready: The candidate values are not available on this dashboard, so they cannot be checked before saving<\/div>/);
  assert.equal(closed.out.cards.c5.state, 'var(--warn)');
  assert.doesNotMatch(closed.out.cards.c5.inner, /Save is allowed once the arm is on/);
  const open = renderScenario('arm_on_ready', { armOnS: 3, elapsedS: 20, ui: SAVE_UI, E: { ...scenarios.arm_on_ready, review_slots: 'unavailable', review_context: 'unavailable' } });
  assert.match(tagOf(open.out.cards.c4.inner, 'save'), /aria-disabled="true"/);
  assert.match(open.out.cards.c4.inner, /Candidate reviewed and saveable<span class="sr"> - unknown<\/span>/);
  // no summary: no "Expected generation 1" for a stored generation 7, no "Would become generation N"
  const noSummary = renderScenario('arm_on_ready', { armOnS: 3, elapsedS: 20, ui: SAVE_UI, E: { ...scenarios.arm_on_ready, summary: 'unavailable' } });
  const t = textNodes(noSummary.out.cards.c4.inner, noSummary.tv);
  assert.equal(t[t.indexOf('Expected generation') + 1], '—');
  assert.equal(t[t.indexOf('Would become') + 1], 'not known: the saved-profile summary is not complete');
  assert.ok(t.includes(`Replaces the saved profile. ${card.FLOW_TEXT.generationUnknown}`));
  assert.ok(!t.some((x) => /Expected result: generation|generation [0-9]/.test(x) && /Expected|become/.test(x)), 'no generation number is derived');
  assert.match(tagOf(noSummary.out.cards.c4.inner, 'save'), /aria-disabled="true"/);
  assert.match(noSummary.out.cards.c5.inner, /<div class="foot warn">Save is not ready: The saved-profile summary is not available, so the generation to be written cannot be shown<\/div>/);
  // a complete screen is unchanged
  assert.match(renderScenario('ready_match').out.cards.c5.inner, /<div class="foot ok">Save is allowed once the arm is on/);
});

test('FB-B2 CARD-12: the outcome heading of a save and the result block of an invalidate can take focus (so the keyboard does not fall to the page when the progress row goes)', () => {
  for (const n of ['saved_ok', 'save_refused_arm', 'save_not_committed', 'save_unknown', 'ready_match', 'idle_saved', 'expired']) {
    const c4 = c4of(n);
    assert.match(c4, /<div class="head" tabindex="-1" data-fk="act-result"><span class="dot[^"]*"><\/span><span class="headline">/, n);
    assert.equal((c4.match(/data-fk="act-result"/g) || []).length, 1, n);
  }
  for (const n of ['invalidated_ok', 'invalidate_refused', 'invalidate_unknown']) {
    assert.equal((c1of(n).match(/data-fk="act-result-inv"/g) || []).length, 1, n);
  }
  assert.doesNotMatch(c1of('idle_saved'), /act-result-inv/, 'no result block, no focus target');
  assert.match(c1of('idle_saved'), /<div class="head" tabindex="-1" data-fk="c1-head">/, 'the fallback target of the invalidate hand-over');
  assert.match(STYLE, /\.head:focus, \.actres \.at:focus \{ outline: none; \}/);
  assert.match(STYLE, /\.head:focus-visible, \.actres \.at:focus-visible \{ outline: 2px solid/);
  // the focus keys are unique inside every render
  for (const n of names) {
    const { out } = renderScenario(n, { ui: { intent: 'save' }, armOnS: 3, elapsedS: 20 });
    const fks = [...html(out).matchAll(/data-fk="([^"]+)"/g)].map((m) => m[1]).filter((k) => !/^(copy-|more-|seg-|scroll-)/.test(k));
    assert.equal(new Set(fks).size, fks.length, `${n}: ${fks.join(',')}`);
  }
});

test('FB-B2 CARD-02: entity text in the top bar, in the review sentences and in the storage rows is escaped too (a sweep of every esc() of the renderers found these unpinned)', () => {
  const payloads = ['<img src=x onerror=a()>', '"><img src=x onerror=a()>', '" onmouseover="a()', "' onmouseover='a()", '"><script>a()</script>'];
  for (const payload of payloads) {
    // the top bar names the supervision state when the heartbeat is not stable
    const bar = renderScenario('ready_match', { E: { ...scenarios.ready_match, supervision_stable: 'off', supervision_state: payload } });
    assertNoInjection(fillTime(bar.out.header, bar.tv), `${payload} / top bar`);
    assert.ok(bar.out.header.includes(card.esc(payload.toLowerCase())), `${payload}: the badge prints the state (lower case), escaped`);
    // the B9 detail in every review state that prints it: the headline sentence of card 3 and the row of card 4
    for (const prefix of ['REVIEW REFUSED - ', 'REVIEW NOT COMPLETED - ', 'REVIEW NOT COMPLETED - configuration changed during the read; ', 'REVIEW CLEARED - ', 'INTERNAL STATE RESET - ']) {
      const r = renderScenario('idle_saved', { E: { ...scenarios.idle_saved, last_result: `${prefix}${payload}` }, ui: { detailOpen: true } });
      for (const id of Object.keys(r.out.cards)) assertNoInjection(fillTime(r.out.cards[id].inner, r.tv), `${payload} / ${prefix}/ ${id}`);
      assert.ok(fillTime(r.out.cards.c3.inner, r.tv).includes(card.esc(payload)), `${prefix}${payload}: card 3 prints the detail, escaped`);
      assert.ok(fillTime(r.out.cards.c4.inner, r.tv).includes(card.esc(payload)), `${prefix}${payload}: card 4 prints the detail, escaped`);
    }
    // the storage condition of an unusable stored profile: load result, defect and witness words come from the summary
    const short = payload.length > 26 ? payload.slice(0, 26) : payload;
    const E = { ...scenarios.unusable, summary: `g=-;id=-;at=-;ld=${short};df=${short};w=${short};hw=-;op=-;why=-;werr=-;us=-` };
    const u = renderScenario('unusable', { E, ui: { detailOpen: true } });
    for (const id of Object.keys(u.out.cards)) assertNoInjection(fillTime(u.out.cards[id].inner, u.tv), `${payload} / storage / ${id}`);
    assert.ok(u.out.cards.c1.inner.includes(`<div>${card.esc(short)}</div>`), 'the load result is printed, escaped');
    assert.ok(u.out.cards.c1.inner.includes(`<div>defect: ${card.esc(short)}</div>`), 'the defect is printed, escaped');
    assert.ok(u.out.cards.c1.inner.includes(`<div>witness: ${card.esc(short)}</div>`), 'the witness word is printed, escaped');
    assert.ok(u.out.cards.c1.inner.includes(`title="${card.esc(`ld=${short} df=${short} w=${short}`)}"`), 'and the tooltip');
  }
});
