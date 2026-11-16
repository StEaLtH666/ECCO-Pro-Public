// Review round 9 ([r9]): THE ASYNC-HIDE CLASS. Reviewer mutants E05 (Promise.resolve().then(() => the strip's text is emptied in Geek Mode)), E07 (the same inside the renderer) and E08 (an async function that awaits
// and then empties the strip) survived every suite: each test looked at the strip in the same task as the click, and the strip was emptied a tick later. The owner's invariant is that a safety alert is visible in
// BOTH modes at ALL times, so the class is "work that the card defers", however it defers it. Three nets close it (async-net.mjs explains them):
//   (1) THE PIN (this file): every way to defer work (Promise, then, catch, async, await, queueMicrotask, setTimeout, setInterval, setImmediate, requestAnimationFrame, requestIdleCallback, MutationObserver,
//       ResizeObserver, IntersectionObserver, PerformanceObserver, addEventListener, an on-property handler ...) is looked for on every line of the card, strings and comments excluded, and each occurrence must be
//       on the ENUMERATED list ALLOWED_ASYNC_SITES, with the reason it exists. Anything new fails until a person decides. The planted forms below are each refused (negative controls).
//   (2) THE SCHEDULER (element.test.mjs, "THE TOUR" and every AC6 test): it records every call the card makes to any of them and runs everything that is waiting, of any delay, after every step, and the strip must be
//       the same strip after each. This file proves the scheduler itself reaches every kind of deferral (negative controls: a synthetic page whose strip is hidden by each of them is seen to change).
//   (3) THE MUTANTS (mutations.test.mjs) and the headless browser check (preview/check-strip.mjs), which measures again after a zero-delay timer and tries to wait for two animation frames (round 10: in a headless run the
//       frames mostly do not come and the wait is given up after 250 ms, so the browser layer covers microtasks, promises and timers of up to 250 ms; animation frames and longer timers are covered only by the node scheduler).
//
// Review round 10 ([r10]) adds the CLOCK class and the BODY class (the reviewer's A04, A05 and A09 survived all 13 suites, although the card itself is right):
//   (4) THE CLOCK PIN and THE CLOCKS: every place where the card reads a clock or a page state is on an enumerated list (ALLOWED_CLOCK_SITES), and every flush moves the clocks the card sees forward by an hour, so a hide that
//       waits for time to pass is triggered; the shift, its total and the number of reads are bounded and throw.
//   (5) THE BODIES: the functions that a continuation (the helpers promise, its rejection, the clipboard) runs may use only the names on a documented list (CONTINUATION_BODIES).
import test, { after, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { CARD_PATH } from './helpers.mjs';
import { installDom, installResizeObserver, MEvent } from './minidom.mjs';
import { ASYNC_TOKENS, ALLOWED_ASYNC_SITES, BOUNDS, SchedulerBound, scanLines, siteKey, asyncOccurrences, asyncSiteProblems, installScheduler, stripFingerprint,
  CLOCK_TOKENS, ALLOWED_CLOCK_SITES, CLOCK_STEP_MS, clockOccurrences, clockSiteProblems, CONTINUATION_BODIES, continuationProblems, readPerformanceNow, readDateNow } from './async-net.mjs';

const src = readFileSync(CARD_PATH, 'utf8');
const GEEK_LINE = "    ui.geekBody.hidden = mode !== 'geek';";
// the two clock calls, written so that this file does not READ a clock in the text of a test (static.test.mjs: a test whose text reads a clock is a wall-clock test and carries the tag; these are only planted text)
const PN = `performance.${'now'}()`;
const DN = `Date.${'now'}()`;
const plantAfter = (anchor, snippet) => {
  assert.equal(src.split(anchor).length - 1, 1, `anchor found once: ${anchor.slice(0, 60)}`);
  return src.replace(anchor, () => `${anchor}\n    ${snippet}`);
};
const planted = (snippet) => plantAfter(GEEK_LINE, snippet);

// ---------------------------------------------------------------------------------------------------------------------------
// (1) the pin
// ---------------------------------------------------------------------------------------------------------------------------
test('async pin [r9]: every place where the card can defer or schedule work is on the enumerated list, each with the reason it exists, and the list has no entry that is not found (strings and comments are not code)', () => {
  const { unlisted, missing } = asyncSiteProblems(src);
  assert.deepEqual(unlisted, [], 'a way to defer work that no person has decided on: read it, then add it to ALLOWED_ASYNC_SITES with its reason in the same commit');
  assert.deepEqual(missing, [], 'a listed site that is gone or changed: update the list');
  assert.ok(ALLOWED_ASYNC_SITES.length >= 10, `${ALLOWED_ASYNC_SITES.length} sites`);
  const seen = new Set();
  for (const a of ALLOWED_ASYNC_SITES) {
    const k = `${a.token}\u0000${siteKey(a.line)}`;
    assert.ok(!seen.has(k), `listed twice: ${a.token} ${a.line}`);
    seen.add(k);
    assert.ok(Object.hasOwn(ASYNC_TOKENS, a.token), `${a.token} is a token the pin looks for`);
    assert.ok(Number.isInteger(a.count) && a.count >= 1, `${a.token}: a count`);
    assert.ok(typeof a.where === 'string' && a.where.length >= 3, `${a.token}: where it is`);
    assert.ok(typeof a.why === 'string' && a.why.length >= 40, `${a.token} in ${a.where}: a reason a person can judge (${a.why.length} characters)`);
    assert.equal(a.line, siteKey(a.line), 'the line is written in its normal form (comments gone, white space folded)');
  }
  // what the card does, by kind: one timer slot, one observer, the window listeners, the element listener helper and the two promise chains
  const by = (tok) => asyncOccurrences(src).filter((o) => o.token === tok).length;
  assert.equal(by('setInterval'), 1);
  assert.equal(by('setTimeout') + by('setImmediate') + by('queueMicrotask') + by('requestAnimationFrame') + by('requestIdleCallback'), 0);
  assert.equal(by('MutationObserver') + by('IntersectionObserver') + by('PerformanceObserver'), 0);
  assert.equal(by('ResizeObserver'), 2);
  assert.equal(by('Promise') + by('async') + by('await') + by('finally'), 0, 'no promise is made, no function is async, nothing is awaited');
  assert.equal(by('then'), 2, 'two promise continuations: the card helpers and the clipboard');
  assert.equal(by('on-property handler'), 0);
});

test('async pin [r9]: the pin looks for every way the owner named (Promise, then, async, await, queueMicrotask, setTimeout, setInterval, requestAnimationFrame, MutationObserver, ResizeObserver, IntersectionObserver) and more', () => {
  for (const t of ['Promise', 'then', 'async', 'await', 'queueMicrotask', 'setTimeout', 'setInterval', 'requestAnimationFrame', 'MutationObserver', 'ResizeObserver', 'IntersectionObserver']) {
    assert.ok(Object.hasOwn(ASYNC_TOKENS, t), t);
  }
  for (const t of ['catch', 'finally', 'setImmediate', 'requestIdleCallback', 'PerformanceObserver', 'MessageChannel', 'nextTick', 'scheduler', 'Worker', 'Atomics', 'AbortSignal', 'addEventListener', 'on-property handler']) {
    assert.ok(Object.hasOwn(ASYNC_TOKENS, t), t);
  }
  for (const re of Object.values(ASYNC_TOKENS)) assert.ok(!re.global && !re.sticky, 'a stateless pattern');
});

test('async pin [r9]: the line reader keeps the line numbers of the file, and a word inside a string, a template, a regular expression or a comment is not code', () => {
  const lines = scanLines(src);
  assert.equal(lines.length, src.split('\n').length, 'one entry per line of the file');
  const sample = [
    "const a = 'then Promise setTimeout async await';", // a string
    'const b = `and then ${x} setInterval`;', // a template (the expression inside is code)
    'const c = /queueMicrotask\'/g;', // a regular expression with a quote in it
    '// requestAnimationFrame in a comment, with an apostrophe: don\'t', // a comment
    '/* then',
    '   await setTimeout */ const d = 1;',
    "const e = \"it's setTimeout\";",
    'const f = `${setTimeout} x`;', // code inside a template expression
  ].join('\n');
  const occ = asyncOccurrences(sample).map((o) => `${o.token}@${o.line}`);
  assert.deepEqual(occ, ['setTimeout@8'], 'only the template EXPRESSION on the last line is code: nothing from the strings, the regular expression and the comments');
  assert.equal(scanLines(sample).length, 8);
});

const NOT_ALLOWED = {
  'E04 queueMicrotask hides the strip': planted("queueMicrotask(() => { ui.strip.hidden = mode === 'geek'; });"),
  'E05 a promise continuation empties the strip': planted("Promise.resolve().then(() => { if (mode === 'geek') ui.strip.textContent = ''; });"),
  'E05b a promise continuation hides the strip': planted('Promise.resolve().then(() => { ui.strip.hidden = true; });'),
  'E07 the renderer empties the strip in a promise continuation': plantAfter('  strip.replaceChildren(...kids);', "Promise.resolve().then(() => { const s = strip.closest('[data-mode]'); if (s && s.getAttribute('data-mode') === 'geek') strip.replaceChildren(); });"),
  'E08 an async function awaits and then empties the strip': planted("(async () => { await null; if (mode === 'geek') ui.strip.replaceChildren(); })();"),
  'an async method': planted('const later = async function later() { return 1; };'),
  'an async arrow': planted('const later = async () => 1;'),
  'for await': planted('const run = async () => { for await (const x of []) { void x; } };'),
  'a thenable': planted('const t = { then(resolve) { resolve(); } };'),
  'a promise made with new': planted('const p = new Promise((resolve) => resolve());'),
  'a finally': planted('p.finally(() => { ui.strip.hidden = true; });'),
  'a catch call': planted('p.catch(() => { ui.strip.hidden = true; });'),
  'setTimeout of zero': planted("setTimeout(() => { ui.strip.hidden = mode === 'geek'; }, 0);"),
  'setTimeout of twenty seconds': planted("setTimeout(() => { ui.strip.hidden = mode === 'geek'; }, 20000);"),
  'a second interval': planted('setInterval(() => { ui.strip.hidden = true; }, 1000);'),
  'a timer reached through the window': planted("window.setTimeout(() => { ui.strip.hidden = true; }, 0);"),
  'setImmediate': planted('setImmediate(() => { ui.strip.hidden = true; });'),
  'process.nextTick': planted('process.nextTick(() => { ui.strip.hidden = true; });'),
  'requestAnimationFrame': planted('requestAnimationFrame(() => { ui.strip.hidden = true; });'),
  'requestAnimationFrame behind a typeof test': planted("if (typeof requestAnimationFrame === 'function') requestAnimationFrame(() => { ui.strip.hidden = true; });"),
  'requestIdleCallback': planted('requestIdleCallback(() => { ui.strip.hidden = true; });'),
  'a mutation observer': planted('new MutationObserver(() => { ui.strip.hidden = true; }).observe(ui.shell, { childList: true });'),
  'an intersection observer': planted('new IntersectionObserver(() => { ui.strip.hidden = true; }).observe(ui.strip);'),
  'a performance observer': planted('new PerformanceObserver(() => { ui.strip.hidden = true; });'),
  'a second resize observer': planted('new ResizeObserver(() => { ui.strip.hidden = true; }).observe(ui.strip);'),
  'a listener on the strip': planted("ui.strip.addEventListener('click', () => { ui.strip.hidden = true; });"),
  'a listener on the window': planted("window.addEventListener('focus', () => { ui.strip.hidden = true; });"),
  'a listener removed': planted("window.removeEventListener('blur', this._onPageHide);"),
  'an on-property handler': planted('ui.shell.onpointerover = () => { ui.strip.hidden = true; };'),
  'a message channel': planted('new MessageChannel().port1.onmessage = () => { ui.strip.hidden = true; };'),
  'scheduler.postTask': planted('scheduler.postTask(() => { ui.strip.hidden = true; });'),
  'an abort signal timeout': planted('AbortSignal.timeout(10);'),
  'a worker': planted("new Worker('x');"),
  'Atomics.waitAsync': planted('Atomics.waitAsync(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 5).value.then(() => {});'),
  'a duplicate of an allowed line (the same timer, twice)': plantAfter(GEEK_LINE, 'this._timer = setInterval(() => this._onTimer(), ms);'),
  'an allowed line, changed (the same call, a different delay)': src.replace('this._timer = setInterval(() => this._onTimer(), ms);', 'this._timer = setInterval(() => this._onTimer(), 1);'),
  'an allowed line, changed (the promise continuation also empties the strip)': src.replace('helpers().then((hp) => attach(hp.createCardElement(cfg)))', "helpers().then((hp) => { attach(hp.createCardElement(cfg)); this._ui.strip.replaceChildren(); })"),
};

test('async pin [r9] has teeth: each planted form (the reviewer mutants E04, E05, E07, E08 and every other way to defer work) is refused, and so are a duplicated and a changed allowed line (negative controls)', () => {
  assert.deepEqual(asyncSiteProblems(src), { unlisted: [], missing: [] }, 'the real card passes');
  for (const [what, text] of Object.entries(NOT_ALLOWED)) {
    assert.notEqual(text, src, `${what}: the plant changed the source`);
    const r = asyncSiteProblems(text);
    assert.ok(r.unlisted.length + r.missing.length > 0, `not refused: ${what}`);
  }
  assert.ok(Object.keys(NOT_ALLOWED).length >= 35);
});

// ---------------------------------------------------------------------------------------------------------------------------
// (1b) [r10] the pin of the clocks and the pin of the bodies of the continuations
// ---------------------------------------------------------------------------------------------------------------------------
test('clock pin [r10]: every place where the card reads a clock or a page state (Date, performance, a timestamp, visibility, focus, the connection, a media query, the card clock) is on the enumerated list, each with its reason; the list has no entry that is not found', () => {
  const { unlisted, missing } = clockSiteProblems(src);
  assert.deepEqual(unlisted, [], 'a clock or page-state read that no person has decided on: read it, then add it to ALLOWED_CLOCK_SITES with its reason in the same commit');
  assert.deepEqual(missing, [], 'a listed site that is gone or changed: update the list');
  const seen = new Set();
  for (const a of ALLOWED_CLOCK_SITES) {
    const k = `${a.token}\u0000${siteKey(a.line)}`;
    assert.ok(!seen.has(k), `listed twice: ${a.token} ${a.line}`);
    seen.add(k);
    assert.ok(Object.hasOwn(CLOCK_TOKENS, a.token), `${a.token} is a token the pin looks for`);
    assert.ok(Number.isInteger(a.count) && a.count >= 1, `${a.token}: a count`);
    assert.ok(typeof a.where === 'string' && a.where.length >= 3, `${a.token}: where it is`);
    assert.ok(typeof a.why === 'string' && a.why.length >= 40, `${a.token} in ${a.where}: a reason a person can judge (${a.why.length} characters)`);
    assert.equal(a.line, siteKey(a.line), 'the line is written in its normal form (comments gone, white space folded)');
  }
  // what the card does, by kind: ONE reading of the wall clock (the card clock), ONE of the monotonic clock (the burst control), no page state of any kind
  const by = (tok) => clockOccurrences(src).filter((o) => o.token === tok).length;
  assert.equal(by('performance'), 1, 'one line reads performance.now');
  assert.equal(by('the card clock'), 3, 'the card clock is defined once and read twice');
  assert.equal(by('Date'), 8, 'eight lines name Date: the parser, three conversions of a known time, the card clock, the burst control, two lines of the time format');
  for (const t of ['Temporal', 'hrtime', 'getTime', 'timeStamp', 'visibilityState', 'document.hidden', 'hasFocus', 'onLine', 'matchMedia']) assert.equal(by(t), 0, `the card never reads ${t}`);
  // the card reads a clock in exactly two ways, and no code reads both through one alias
  assert.equal((src.match(/\bDate\.now\b/g) || []).length, 2, 'Date.now: the card clock and the fallback of the burst control');
  assert.equal((src.match(/\bperformance\.now\b/g) || []).length, 2, 'performance.now: the feature test and the call, on one line');
  assert.ok(Object.isFrozen(CLOCK_TOKENS) && Object.isFrozen(ALLOWED_CLOCK_SITES));
  for (const re of Object.values(CLOCK_TOKENS)) assert.ok(!re.global && !re.sticky, 'a stateless pattern');
});

test('clock pin [r10]: the pin looks for every clock and page state the review named (Date.now, performance.now, new Date, a timestamp, visibilityState, document.hidden, hasFocus) and more', () => {
  for (const t of ['Date', 'performance', 'Temporal', 'hrtime', 'getTime', 'timeStamp', 'visibilityState', 'document.hidden', 'hasFocus', 'onLine', 'matchMedia', 'the card clock']) assert.ok(Object.hasOwn(CLOCK_TOKENS, t), t);
});

const plantClock = (anchor, snippet) => {
  assert.equal(src.split(anchor).length - 1, 1, `anchor found once: ${anchor.slice(0, 60)}`);
  return src.replace(anchor, () => `${anchor}\n    ${snippet}`);
};
const NOT_ALLOWED_CLOCKS = {
  'A04 a hide armed with the card clock when the Geek surface is built': plantClock('        this._geek.build();', 'this._geek.bornAt = this._now();'),
  'A05 a hide armed with performance.now': plantClock('        this._geek.build();', `this._geek.bornAt = ${PN};`),
  'a hide armed with Date.now': planted(`this._born = ${DN};`),
  'a clock read through an alias': planted('const clock = Date; this._born = clock.now();'),
  'a new Date with no argument': planted('this._born = new Date();'),
  'a Date.parse of a made-up text': planted("this._born = Date.parse('2026-01-01');"),
  'getTime': planted('this._born = new Date(0).getTime();'),
  'the high resolution clock': planted('this._born = process.hrtime();'),
  'Temporal': planted('this._born = Temporal.Now.instant();'),
  'visibilityState': planted("if (this.ownerDocument.visibilityState === 'hidden') ui.strip.replaceChildren();"),
  'document.hidden': planted('if (this.ownerDocument.hidden) ui.strip.replaceChildren();'),
  'hasFocus': planted('if (!this.ownerDocument.hasFocus()) ui.strip.replaceChildren();'),
  'the connection': planted('if (!navigator.onLine) ui.strip.replaceChildren();'),
  'a media query': planted("if (window.matchMedia('(max-width: 400px)').matches) ui.strip.replaceChildren();"),
  'the timestamp of an event': plantAfter("      on(b, 'click', () => this._ctl.set(mode));", 'on(b, \'click\', (ev) => { if (ev.timeStamp > 60000) this._ui.strip.replaceChildren(); });'),
  'a third read of the card clock': planted('void this._now();'),
  'a duplicate of an allowed line (the card clock, twice)': plantAfter(GEEK_LINE, `this._now = () => ${DN};`),
  'an allowed line, changed (the card clock runs a minute ahead)': src.replace(`this._now = () => ${DN};`, `this._now = () => ${DN} + 60000;`),
  'an allowed line, changed (the burst control reads the other clock)': src.replace(`const t = typeof performance !== 'undefined' && typeof performance.now === 'function' ? ${PN} : ${DN};`, `const t = ${DN};`),
};

test('clock pin [r10] has teeth: each planted way to read a clock or a page state (the reviewer mutants A04 and A05 and every other form) is refused, and so are a duplicated and a changed allowed line (negative controls)', () => {
  assert.deepEqual(clockSiteProblems(src), { unlisted: [], missing: [] }, 'the real card passes');
  for (const [what, text] of Object.entries(NOT_ALLOWED_CLOCKS)) {
    assert.notEqual(text, src, `${what}: the plant changed the source`);
    const r = clockSiteProblems(text);
    assert.ok(r.unlisted.length + r.missing.length > 0, `not refused: ${what}`);
  }
  assert.ok(Object.keys(NOT_ALLOWED_CLOCKS).length >= 18);
  // the line reader sees through the disguises that are not code: a clock in a string, a template text or a comment is not a clock
  const sample = [`const a = '${DN} ${PN} visibilityState';`, 'const b = `at ${x} the Date`;', '// new Date()', 'const c = /Date/g;'].join('\n');
  assert.deepEqual(clockOccurrences(sample).map((o) => `${o.token}@${o.line}`), [], 'only code counts');
  assert.deepEqual(clockOccurrences(`const t = \`\${${DN}}\`;`).map((o) => o.token), ['Date'], 'but the expression inside a template is code');
});

test('body pin [r10]: the functions that a continuation runs (attach, fail, the notice, say and the Geek surface\'s say) use only the names on their documented lists: the strip, the shell, ui, the host and the renderer are on none', () => {
  assert.deepEqual(continuationProblems(src), [], 'a name that no person has decided on: read it, then add it to CONTINUATION_BODIES with its reason in the same commit');
  assert.equal(CONTINUATION_BODIES.length, 5);
  const names = new Set();
  for (const spec of CONTINUATION_BODIES) {
    assert.ok(!names.has(spec.name), `listed twice: ${spec.name}`);
    names.add(spec.name);
    assert.ok(typeof spec.why === 'string' && spec.why.length >= 40, `${spec.name}: a reason`);
    assert.ok(Array.isArray(spec.vocabulary) && spec.vocabulary.length >= 3 && spec.vocabulary.length <= 16, `${spec.name}: a short list`);
    // the names that would reach the alert strip, the shell or a mode are on NO list (a list that names one is a decision to be read, not a default)
    if (spec.name !== 'GeekSurface.say') for (const bad of ['ui', '_ui', 'strip', 'shell', '_root', 'shadowRoot', 'host', 'renderAlertStrip', '_alerts', '_snap', '_ctl', 'querySelector', 'parentNode', 'closest', 'hidden', 'replaceChildren', 'textContent', 'setAttribute', 'remove']) {
      assert.ok(!spec.vocabulary.includes(bad), `${spec.name}: the list names ${bad}`);
    }
    assert.ok(spec.vocabulary.every((w) => /^[A-Za-z_][\w$]*$/.test(w)), `${spec.name}: names only`);
  }
  // the three places where the continuations are started are the three on the pin of the deferrals, and each calls only a function of this list
  const started = ALLOWED_ASYNC_SITES.filter((a) => a.token === 'then' || a.token === 'catch').map((a) => a.line);
  assert.ok(started.some((l) => l.includes('attach(') && l.includes('fail(')) && started.some((l) => l.includes('say(')), 'the helpers promise runs attach and fail; the clipboard promise runs say');
});

const planBody = (from, to) => {
  assert.equal(src.split(from).length - 1, 1, `anchor found once: ${from.slice(0, 70)}`);
  return src.replace(from, () => to);
};
const ATTACH_END = '      if (this._hass !== null && this._hass !== undefined) el.hass = this._hass;';
const FAIL_LINE = "      if (gen === this._gen) wrap.appendChild(this._notice('data-child-error', `Card could not be shown: ${message}`));";
const SAY_LINE = '      if (this._geek) this._geek.say(m);';
const GEEK_SAY = '    if (this.ui.status_line) this.ui.status_line.textContent = text;';
const NOTICE_LINE = "    return mk(doc, 'div', { class: 'notice', [flag]: '', role: 'note' }, cleanText(text, 400));";
const BAD_BODIES = {
  'A09 attach empties the strip in Geek Mode': planBody(ATTACH_END, `${ATTACH_END}\n      if (this._ctl.mode === 'geek') this._ui.strip.replaceChildren();`),
  'attach hides the strip through ui': planBody(ATTACH_END, `${ATTACH_END}\n      ui.strip.hidden = true;`),
  'attach looks the strip up through the root': planBody(ATTACH_END, `${ATTACH_END}\n      this._root.querySelector('[data-ecco-alert-strip]').replaceChildren();`),
  'attach hides the host': planBody(ATTACH_END, `${ATTACH_END}\n      this.hidden = true;`),
  'attach calls the renderer with no alerts': planBody(ATTACH_END, `${ATTACH_END}\n      renderAlertStrip(this.ownerDocument, this._ui.strip, []);`),
  'attach rebuilds the Geek surface': planBody(ATTACH_END, `${ATTACH_END}\n      this._applyMode();`),
  'attach changes the mode': planBody(ATTACH_END, `${ATTACH_END}\n      this._ctl.reset();`),
  'attach reaches the strip through the wrapper': planBody(ATTACH_END, `${ATTACH_END}\n      wrap.parentNode.parentNode.replaceChildren();`),
  'fail empties the strip (the fail variant of A09)': planBody(FAIL_LINE, `${FAIL_LINE}\n      if (this._ctl.mode === 'geek') this._ui.strip.replaceChildren();`),
  'fail empties the strip in Production': planBody(FAIL_LINE, `${FAIL_LINE}\n      this._ui.strip.textContent = '';`),
  'fail sets aria-hidden on the shell': planBody(FAIL_LINE, `${FAIL_LINE}\n      this._ui.shell.setAttribute('aria-hidden', 'true');`),
  'the notice reaches the strip': planBody(NOTICE_LINE, `    this._ui.strip.hidden = true;\n${NOTICE_LINE}`),
  'say empties the strip (the say variant of A09)': planBody(SAY_LINE, `${SAY_LINE}\n      this._ui.strip.replaceChildren();`),
  'say hides the strip when the surface says something': planBody(SAY_LINE, "      if (this._geek) { this._geek.say(m); this._ui.strip.hidden = true; }"),
  'say empties the strip through the shell': planBody(SAY_LINE, `${SAY_LINE}\n      this._ui.shell.replaceChildren();`),
  "the Geek surface's say reaches the strip through its container": planBody(GEEK_SAY, `${GEEK_SAY}\n    this.o.container.parentNode.querySelector('[data-ecco-alert-strip]').replaceChildren();`),
  "the Geek surface's say writes to the document": planBody(GEEK_SAY, `${GEEK_SAY}\n    this.doc.body.hidden = true;`),
  'a second function of the same name (a header found twice)': planBody('    const say = (m) => {', "    const say = (m) => {\n      void m;\n    };\n    const say = (m) => {"),
  'a body that never closes (the header is there, the end is not)': planBody(SAY_LINE, `${SAY_LINE}\n      {`),
};

test('body pin [r10] has teeth: each planted continuation that touches the strip, the shell, the host or the mode (the reviewer mutant A09 and its fail and say variants, and more) is refused, and so is a header found twice or a body that does not close (negative controls)', () => {
  assert.deepEqual(continuationProblems(src), [], 'the real card passes');
  for (const [what, text] of Object.entries(BAD_BODIES)) {
    assert.notEqual(text, src, `${what}: the plant changed the source`);
    assert.ok(continuationProblems(text).length > 0, `not refused: ${what}`);
  }
  assert.ok(Object.keys(BAD_BODIES).length >= 18);
  // a name of the list used in another way is not a change the pin can see (the list is names, not statements): the dynamic half is the AC6 tests that settle a late child, a rejected one and a late clipboard answer
  assert.deepEqual(continuationProblems(planBody(ATTACH_END, `${ATTACH_END}\n      this._kids.push(el);`)), [], 'a list of names, not of statements (documented limit): the async tests of element.test.mjs are the other half');
});

// ---------------------------------------------------------------------------------------------------------------------------
// (2) the scheduler reaches every kind of deferral (negative controls for the net itself)
// ---------------------------------------------------------------------------------------------------------------------------
const { doc, win } = installDom();
const ros = installResizeObserver();
const sched = installScheduler({ resizeObservers: ros });
after(() => sched.uninstall());
beforeEach(() => sched.beginTest());

/** A synthetic card: a host with a shadow root, a shell and a strip with two alerts in it (the fingerprint is the real one). */
function page() {
  const host = new globalThis.HTMLElement();
  const root = host.attachShadow();
  const shell = doc.createElement('div');
  shell.setAttribute('data-ecco-shell', '');
  const strip = doc.createElement('div');
  strip.setAttribute('data-ecco-alert-strip', '');
  strip.setAttribute('role', 'region');
  for (const id of ['A01', 'A02']) {
    const line = doc.createElement('div');
    line.setAttribute('data-alert-id', id);
    line.textContent = `alert ${id}`;
    strip.appendChild(line);
  }
  shell.appendChild(strip);
  root.appendChild(shell);
  return { host, shell, strip };
}

const DEFERRALS = {
  'a promise continuation (E05)': (p) => { Promise.resolve().then(() => { p.strip.textContent = ''; }); },
  'an async function that awaits (E08)': (p) => { (async () => { await null; p.strip.replaceChildren(); })(); },
  'a promise that resolves later': (p) => { new Promise((r) => r()).then(() => null).then(() => { p.strip.hidden = true; }); },
  'queueMicrotask (E04)': (p) => { queueMicrotask(() => { p.strip.hidden = true; }); },
  'a timer of zero': (p) => { setTimeout(() => { p.strip.hidden = true; }, 0); },
  'a timer of twenty seconds': (p) => { setTimeout(() => { p.strip.textContent = ''; }, 20000); },
  'an interval': (p) => { setInterval(() => { p.strip.hidden = true; }, 15000); },
  'setImmediate-style chain: a timer that starts a microtask that starts a frame': (p) => { setTimeout(() => queueMicrotask(() => requestAnimationFrame(() => { p.strip.hidden = true; })), 10); },
  'an animation frame': (p) => { requestAnimationFrame(() => { p.strip.hidden = true; }); },
  'an idle callback': (p) => { requestIdleCallback(() => { p.strip.hidden = true; }); },
  'a mutation observer': (p) => { new MutationObserver(() => { p.strip.hidden = true; }).observe(p.shell, { childList: true }); },
  'an intersection observer (only when it says the strip is not visible)': (p) => { new IntersectionObserver((entries) => { if (entries.some((e) => !e.isIntersecting)) p.strip.hidden = true; }).observe(p.strip); },
  'a resize observer': (p) => { new ResizeObserver(() => { p.strip.hidden = true; }).observe(p.host); },
  'a listener on the strip (click)': (p) => { p.strip.addEventListener('click', () => { p.strip.hidden = true; }); },
  'a listener on the shell (an event no one fires in a test)': (p) => { p.shell.addEventListener('pointerover', () => { p.strip.hidden = true; }); },
  'a listener on the window': (p) => { win.addEventListener('focus', () => { p.strip.hidden = true; }); },
};

test('async net [r9] control: a card that defers nothing is the same strip after everything has run, and a flush with nothing pending returns at once', async () => {
  const p = page();
  const before = stripFingerprint(p.host);
  const ran = await sched.flush({ events: true });
  assert.equal(stripFingerprint(p.host), before);
  assert.equal(typeof ran, 'number');
  assert.equal(sched.pending, 0);
});

for (const [what, defer] of Object.entries(DEFERRALS)) {
  test(`async net [r9] has teeth: ${what} changes the strip, and the scheduler runs it (so a card that did this could not pass the tour)`, async () => {
    sched.resetListeners();
    const p = page();
    const before = stripFingerprint(p.host);
    defer(p);
    assert.equal(stripFingerprint(p.host), before, 'nothing has happened yet: the change is deferred');
    await sched.flush({ events: true });
    assert.notEqual(stripFingerprint(p.host), before, `the scheduler did not reach: ${what}`);
    await sched.flush({ events: true });
    sched.resetListeners();
    sched.clearAll();
  });
}

test('async net [r9] the fingerprint sees every way the strip can differ: its text, its attributes, a hidden or inert ancestor, a child removed, a wrapper, a sibling before it (and not the mode)', () => {
  const same = (p) => stripFingerprint(p.host);
  const ref = same(page());
  assert.equal(same(page()), ref, 'two identical pages are the same');
  const plants = {
    'text': (p) => { p.strip.firstChild.textContent = 'x'; },
    'an attribute on the strip': (p) => p.strip.setAttribute('aria-hidden', 'true'),
    'hidden on the strip': (p) => { p.strip.hidden = true; },
    'a line removed': (p) => p.strip.removeChild(p.strip.firstChild),
    'hidden on the shell': (p) => { p.shell.hidden = true; },
    'inert on the host': (p) => p.host.setAttribute('inert', ''),
    'a style on a line': (p) => p.strip.firstChild.setAttribute('style', 'display:none'),
    'a sibling before the strip': (p) => p.shell.insertBefore(doc.createElement('div'), p.strip),
    'a wrapper': (p) => { const w = doc.createElement('div'); p.shell.appendChild(w); w.appendChild(p.strip); },
    'moved out of the shell': (p) => p.host.shadowRoot.appendChild(p.strip),
  };
  for (const [what, plant] of Object.entries(plants)) {
    const p = page();
    plant(p);
    assert.notEqual(same(p), ref, `not seen: ${what}`);
  }
  // the mode and the theme are the two things that change on purpose: they are not part of it
  const p = page();
  p.shell.setAttribute('data-mode', 'geek');
  p.host.setAttribute('data-theme', 'dark');
  assert.equal(same(p), ref);
  assert.equal(stripFingerprint({ shadowRoot: null }), 'NO STRIP');
});

test('async net [r9] the scheduler: timers of any delay, intervals once per flush, cleared ones never, an event of every registered kind once, and the recorded card lines map to the file', async () => {
  const ran = [];
  const t0 = setTimeout(() => ran.push('timeout 5 s'), 5000);
  const t1 = setTimeout(() => ran.push('cleared'), 10);
  clearTimeout(t1);
  const iv = setInterval(() => ran.push('interval'), 60000);
  requestAnimationFrame((ts) => ran.push(`frame ${typeof ts}`));
  cancelAnimationFrame(requestAnimationFrame(() => ran.push('cancelled frame')));
  queueMicrotask(() => ran.push('microtask'));
  Promise.resolve().then(() => ran.push('promise'));
  const target = doc.createElement('div');
  doc.body.appendChild(target); // an element that is not on the page is not fired at (it can never be reached), so this one is put on the page
  target.addEventListener('click', () => ran.push('click'));
  target.addEventListener('click', () => ran.push('click 2'));
  const steps = [];
  await sched.flush({ events: true, after: (what) => steps.push(what) });
  assert.deepEqual(ran.filter((x) => x !== 'click 2').sort(), ['click', 'frame number', 'interval', 'microtask', 'promise', 'timeout 5 s']);
  assert.equal(ran.filter((x) => x === 'interval').length, 1, 'an interval runs once per flush');
  assert.ok(steps.length >= 6 && steps.includes('an animation frame'), steps.join(' | '));
  assert.ok(steps.some((s) => /a click event on div/.test(s)), 'an event is fired once per target and kind, and each fire is a step');
  assert.equal(ran.filter((x) => x === 'click').length, 1, 'one click event for the pair (target, click): its two handlers both run');
  assert.equal(ran.filter((x) => x === 'click 2').length, 1);
  target.remove();
  clearInterval(iv);
  clearTimeout(t0);
  assert.equal(sched.pending, 0);
  // the calls made here are the test's own, not the card's: none is recorded as the card's
  assert.equal(sched.records.length, 0, 'this file never loads the card');
  // a MEvent is the event the scheduler fires
  assert.equal(new MEvent('click').type, 'click');
});

// ---------------------------------------------------------------------------------------------------------------------------
// (2b) [r10] THE CLOCKS the card sees. The reviewer's A04 and A05 emptied the strip when a clock was a minute (twenty seconds) past the moment the Geek surface was built; no test ever moved a clock. Every flush now moves
// performance.now and Date.now forward by an hour for the card (never back); everyone else's clocks are the real ones. Count-based: no test below measures how long anything took.
// ---------------------------------------------------------------------------------------------------------------------------
/** [real, moved, real]: the clock read as a test reads it, as the card would read it (scope 'tracked'), and as a test reads it again. Moved is between the two reals when nothing has moved it, and that far ahead of them when something has. */
const trio = (read) => {
  const a = read();
  const b = sched.withClockScope('tracked', read);
  const c = read();
  return [a, b, c];
};

for (const [name, read] of [['performance.now', readPerformanceNow], ['Date.now', readDateNow]]) {
  test(`async net [r10] THE CLOCKS: ${name}, as the card reads it, moves forward by an hour at every flush and never back; the real clock of a test is left alone; a step of zero moves nothing`, async () => {
    let [a, b, c] = trio(read);
    assert.ok(b >= a && b <= c, 'before any flush the card sees the real clock');
    assert.deepEqual({ ...sched.clock, reads: 0 }, { shiftMs: 0, steps: 0, reads: 0, scope: 'card' });
    await sched.flush();
    [a, b, c] = trio(read);
    assert.ok(b >= a + CLOCK_STEP_MS && b <= c + CLOCK_STEP_MS, 'after one flush: an hour ahead');
    assert.ok(c - a < CLOCK_STEP_MS / 2, 'and the clock of the test is still the real one');
    await sched.flush();
    [a, b, c] = trio(read);
    assert.ok(b >= a + 2 * CLOCK_STEP_MS && b <= c + 2 * CLOCK_STEP_MS, 'after two: two hours');
    await sched.flush({ clockStepMs: 0 });
    [a, b, c] = trio(read);
    assert.ok(b >= a + 2 * CLOCK_STEP_MS && b <= c + 2 * CLOCK_STEP_MS, 'a step of zero moves nothing');
    await sched.flush({ clockStepMs: 90000 });
    [a, b, c] = trio(read);
    assert.ok(b >= a + 2 * CLOCK_STEP_MS + 90000 && b <= c + 2 * CLOCK_STEP_MS + 90000, 'a step of ninety seconds is ninety seconds');
    assert.deepEqual({ shiftMs: sched.clock.shiftMs, steps: sched.clock.steps }, { shiftMs: 2 * CLOCK_STEP_MS + 90000, steps: 4 });
    assert.equal(sched.clock.reads, 5, 'only the reads of the card (here, of the tracked scope) are counted, one per trio');
    sched.beginTest();
    assert.deepEqual({ ...sched.clock }, { shiftMs: 0, steps: 0, reads: 0, scope: 'card' }, 'a new test starts with the real clocks');
  });
}

test('async net [r10] THE CLOCKS: a flush with the moved clocks does not disturb a measurement made around it (the test reads its own clock; the card reads the moved one)', async () => {
  const t0 = readPerformanceNow();
  await sched.flush();
  await sched.flush();
  const t1 = readPerformanceNow();
  assert.ok(t1 - t0 < CLOCK_STEP_MS / 2, 'two flushes took far less than the hour they moved the card by');
  const d0 = readDateNow();
  await sched.flush();
  assert.ok(readDateNow() - d0 < CLOCK_STEP_MS / 2);
});

/** A synthetic page whose strip is emptied by a gate on a clock; `arm` says when the gate is set. */
const CLOCK_GATES = {
  'a hide that waits a minute after the switch, on performance.now (reviewer mutant A05)': (p) => { const born = readPerformanceNow(); setInterval(() => { if (readPerformanceNow() - born >= 60000) p.strip.replaceChildren(); }, 15000); },
  'a hide that waits twenty seconds, on Date.now': (p) => { const born = readDateNow(); setInterval(() => { if (readDateNow() - born >= 20000) p.strip.hidden = true; }, 15000); },
  'a hide that waits a whole day, on performance.now (a timer of an hour is not enough: the flushes add up)': (p) => { const born = readPerformanceNow(); setInterval(() => { if (readPerformanceNow() - born >= 20 * 3600000) p.strip.replaceChildren(); }, 15000); },
  'a hide armed INSIDE a flush and sprung in a later one': (p) => { setTimeout(() => { const born = readDateNow(); setInterval(() => { if (readDateNow() - born >= 30 * 60000) p.strip.hidden = true; }, 15000); }, 10); },
  'a hide once the page has been open three hours (an absolute threshold on performance.now)': (p) => { setInterval(() => { if (readPerformanceNow() > 3 * 3600000) p.strip.hidden = true; }, 15000); },
};

for (const [what, gate] of Object.entries(CLOCK_GATES)) {
  test(`async net [r10] has teeth: ${what}: it is armed, nothing happens on a frozen clock (the control), and it fires once the clocks have moved (within 21 flushes: an hour each)`, async () => {
    // the control: with clock steps of ZERO the gate never opens, whatever the number of flushes (a test with a frozen clock: what every test did before round 10)
    await sched.withBounds({}, async () => {
      const frozen = page();
      const before = stripFingerprint(frozen.host);
      gate(frozen);
      for (let i = 0; i < 3; i += 1) await sched.flush({ clockStepMs: 0 });
      assert.equal(stripFingerprint(frozen.host), before, 'a frozen clock never opens the gate (this is what survived)');
    }, { clockScope: 'tracked' });
    // the same gate on a fresh page and a fresh clock, with the steps of an hour (a hard bound of 24 flushes)
    await sched.withBounds({}, async () => {
      const moving = page();
      const start = stripFingerprint(moving.host);
      gate(moving);
      let flushes = 0;
      for (; flushes < 24 && stripFingerprint(moving.host) === start; flushes += 1) await sched.flush();
      assert.notEqual(stripFingerprint(moving.host), start, `${what}: not reached after ${flushes} flushes`);
      assert.ok(flushes <= 21, `${flushes} flushes`);
    }, { clockScope: 'tracked' });
  });
}

test('async net [r10] BOUNDED: the clock steps, their total and the readings of the clock each have a bound that throws at once (a step that is not a finite number of milliseconds, a step beyond a day, a total beyond 2000 hours, a card that reads a clock in a loop)', async () => {
  assert.ok(Object.isFrozen(BOUNDS));
  for (const k of ['maxClockStepMs', 'maxClockShiftMs', 'maxClockReads']) assert.ok(Number.isInteger(BOUNDS[k]) && BOUNDS[k] > 0, k);
  assert.ok(CLOCK_STEP_MS > 0 && CLOCK_STEP_MS <= BOUNDS.maxClockStepMs && BOUNDS.maxClockStepMs <= BOUNDS.maxClockShiftMs, 'the default step is inside the bounds');
  // a step that is not a number of milliseconds, zero or more, and finite
  for (const bad of [-1, Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY, '3600000', null, 1e12, BOUNDS.maxClockStepMs + 1]) {
    await sched.withBounds({}, async () => {
      await assert.rejects(() => sched.flush({ clockStepMs: bad }), (e) => e instanceof SchedulerBound && e.which === 'maxClockStepMs', `a step of ${String(bad)} is refused`);
      assert.equal(sched.clock.shiftMs, 0, 'and nothing was moved');
      assert.ok(sched.failure instanceof SchedulerBound, 'the scheduler remembers it');
      await assert.rejects(() => sched.flush(), (e) => e === sched.failure, 'and a later flush raises it again');
    });
  }
  // the biggest step that is allowed
  await sched.withBounds({}, async () => {
    await sched.flush({ clockStepMs: BOUNDS.maxClockStepMs });
    assert.equal(sched.clock.shiftMs, BOUNDS.maxClockStepMs);
  });
  // the total: three steps of two hours against a bound of five
  await sched.withBounds({ maxClockShiftMs: 5 * 3600000 }, async () => {
    await sched.flush({ clockStepMs: 2 * 3600000 });
    await sched.flush({ clockStepMs: 2 * 3600000 });
    await assert.rejects(() => sched.flush({ clockStepMs: 2 * 3600000 }), (e) => e instanceof SchedulerBound && e.which === 'maxClockShiftMs' && e.seen === 6 * 3600000 && e.limit === 5 * 3600000);
    assert.equal(sched.clock.shiftMs, 4 * 3600000, 'the step that crossed the bound was not taken');
  });
  // the number of flushes is bounded by the same total: a loop of flushes of the default step stops by itself
  await sched.withBounds({ maxClockShiftMs: 10 * CLOCK_STEP_MS }, async () => {
    let n = 0;
    await assert.rejects(async () => { for (; n < 1000; n += 1) await sched.flush(); }, (e) => e instanceof SchedulerBound && e.which === 'maxClockShiftMs');
    assert.equal(n, 10, 'ten flushes, then the eleventh throws');
  });
  // a card that reads a clock in a loop, and swallows the error: every read counts, the bound is raised by the next flush, and every later read throws the same error
  await sched.withBounds({ maxClockReads: 40 }, async () => {
    let caught = null;
    let reads = 0;
    for (let i = 0; i < 100; i += 1) {
      try {
        readPerformanceNow();
        readDateNow();
        reads += 2;
      } catch (e) {
        caught = e;
      }
    }
    assert.equal(caught, null, 'the scope is the card: a test reading its own clock is not counted');
    assert.equal(reads, 200);
  });
  await sched.withBounds({ maxClockReads: 40 }, async () => {
    let first = null;
    let made = 0;
    for (let i = 0; i < 100; i += 1) {
      try {
        made += 1;
        readPerformanceNow();
        readDateNow();
      } catch (e) {
        first = first || e;
        assert.equal(e, first, 'the same error every time');
      }
    }
    assert.ok(first instanceof SchedulerBound && first.which === 'maxClockReads' && first.limit === 40 && first.seen === 41, String(first));
    assert.equal(made, 100, 'the loop was the card\'s own: it ran on, and every read from the 41st threw');
    await assert.rejects(() => sched.flush(), (e) => e === first, 'the flush raises it, however the card swallowed it');
  }, { clockScope: 'tracked' });
  assert.equal(sched.failure, null);
  assert.equal(sched.clock.shiftMs, 0);
  assert.equal(sched.clock.scope, 'card', 'and the scope is the default again');
  assert.throws(() => sched.withClockScope('everyone', () => 0), RangeError);
  assert.throws(() => installScheduler({ clockScope: 'nobody' }), RangeError);
});

// ---------------------------------------------------------------------------------------------------------------------------
// (3) THE SCHEDULER CANNOT RUN AWAY. Two earlier attempts of review round 9 were killed because the machine ran out of virtual memory: the first version of the scheduler fired events at every listener it had ever seen, the
// events re-rendered, the re-renders registered more listeners, and the heap grew without end. Now every kind of work the scheduler records, runs or fires has a hard maximum (BOUNDS), and a card that keeps re-arming
// work in its own handlers makes the flush THROW a SchedulerBound at once. The cards below are synthetic pages that do exactly that (the real card is not loaded in this file). One test proves WHICH bound stops each of
// them and after how much work (a count, no clock); the other proves that it is quick and that the heap stays small (the clock and the heap: tagged [wall-clock] for the mutation runner).
// ---------------------------------------------------------------------------------------------------------------------------
const heapMB = () => process.memoryUsage().heapUsed / (1024 * 1024);

/** Every runaway card: how it is planted, the bound that must stop it, and how much it may have made by then. `plant(page, state)`; `state.made` counts what the card made. */
const growButtons = (p, s) => {
  const grow = (parent) => {
    for (let i = 0; i < 20; i += 1) {
      s.made += 1;
      const b = doc.createElement('button');
      parent.appendChild(b);
      b.addEventListener('click', () => grow(parent));
    }
  };
  grow(p.shell);
};
const RUNAWAYS = [
  { name: 'a timer that re-arms itself in its own handler', expect: 'maxRounds', maxMade: 10,
    plant: (p, s) => { const again = () => { s.made += 1; setTimeout(again, 5000); }; again(); } },
  { name: 'an animation frame that asks for the next frame in its own callback', expect: 'maxRounds', maxMade: 10,
    plant: (p, s) => { const again = () => { s.made += 1; requestAnimationFrame(again); }; again(); } },
  { name: 'an interval whose callback starts another interval (the number of intervals doubles at every flush)', expect: 'maxPending', bounds: { maxPending: 40 }, maxMade: 200,
    plant: (p, s) => { const spawn = () => { s.made += 1; setInterval(spawn, 15000); }; spawn(); } },
  { name: 'a microtask that queues the next microtask for ever (the macrotask never comes)', expect: 'maxWorkPerTest', bounds: { maxWorkPerTest: 2000 }, maxMade: 2100,
    plant: (p, s) => { const loop = () => { s.made += 1; try { queueMicrotask(loop); } catch (e) { s.caught = e; } }; loop(); } },
  { name: 'a promise continuation that makes the next promise continuation for ever', expect: 'maxWorkPerTest', bounds: { maxWorkPerTest: 2000 }, maxMade: 2100,
    plant: (p, s) => { const loop = () => { s.made += 1; try { Promise.resolve().then(loop); } catch (e) { s.caught = e; } }; loop(); } },
  { name: 'a click handler that makes twenty buttons with the same handler (the number of listeners grows twentyfold at every flush): too many to fire at', expect: 'maxEventsPerFlush', bounds: { maxEventsPerFlush: 300 }, maxMade: 500,
    plant: growButtons },
  { name: 'the same, with room to fire but not to hold: too many listeners alive', expect: 'maxListeners', bounds: { maxListeners: 300, maxEventsPerFlush: 100000 }, maxMade: 400,
    plant: growButtons },
  { name: 'a handler on the window that registers three more listeners on the window for every event it gets', expect: 'maxListeners', bounds: { maxListeners: 60 }, maxMade: 200,
    plant: (p, s) => { const add = () => { for (const type of ['focus', 'blur', 'resize']) { s.made += 1; win.addEventListener(`${type}${s.made}`, add); } }; add(); } },
  { name: 'a resize observer whose callback makes another resize observer', expect: 'maxCallbacksPerFlush', bounds: { maxCallbacksPerFlush: 50 }, maxMade: 200,
    plant: (p, s) => { const make = () => { s.made += 1; new ResizeObserver(() => make()).observe(p.host); }; make(); } },
  { name: 'a timer callback that reads the clock five thousand times and swallows the error (round 10: every read of the card is counted, and the bound is raised by the flush all the same)', expect: 'maxClockReads', bounds: { maxClockReads: 1500 }, scope: 'tracked', maxMade: 5000,
    plant: (p, s) => { setTimeout(() => { for (let i = 0; i < 5000; i += 1) { try { s.made += 1; readPerformanceNow(); } catch (e) { s.caught = e; } } }, 10); } },
  { name: 'a listener that swallows the error: the bound is raised by the flush all the same', expect: 'maxListeners', bounds: { maxListeners: 100 }, maxMade: 600,
    plant: (p, s) => {
      p.shell.addEventListener('click', () => {
        for (let i = 0; i < 500; i += 1) {
          try {
            s.made += 1;
            const b = doc.createElement('b');
            p.shell.appendChild(b);
            b.addEventListener('x', () => {});
          } catch (e) {
            s.caught = e;
          }
        }
      });
    } },
];

async function runRunaway(r) {
  const s = { made: 0, caught: null };
  const seen = await sched.withBounds(r.bounds || {}, async () => {
    const p = page();
    r.plant(p, s);
    let err = null;
    let flushes = 0;
    try {
      for (; flushes < 60; flushes += 1) await sched.flush({ events: true });
    } catch (e) {
      err = e;
    }
    const failure = sched.failure;
    let again = null;
    try {
      await sched.flush();
    } catch (e) {
      again = e;
    }
    for (const o of ros) o.disconnected = true;
    return { err, flushes, failure, again };
  }, r.scope ? { clockScope: r.scope } : {});
  return { ...seen, s };
}

test('async net [r9] BOUNDED: every runaway card (a timer, a frame, an interval, a microtask, a promise, a listener, an observer that re-arms itself) is stopped by a named bound, after a bounded amount of work, and the error is remembered', async () => {
  assert.ok(Object.isFrozen(BOUNDS));
  for (const k of Object.keys(BOUNDS)) assert.ok(Number.isInteger(BOUNDS[k]) && BOUNDS[k] > 0, k);
  assert.equal(RUNAWAYS.length >= 10, true);
  for (const r of RUNAWAYS) {
    const out = await runRunaway(r);
    assert.ok(out.err instanceof SchedulerBound, `${r.name}: it was not stopped (${out.err}), after ${out.flushes} flushes`);
    assert.equal(out.err.which, r.expect, `${r.name}: ${out.err.message}`);
    assert.ok(out.flushes < 60, `${r.name}: ${out.flushes} flushes`);
    assert.ok(out.s.made <= r.maxMade, `${r.name}: it made ${out.s.made} things before it was stopped (at most ${r.maxMade})`);
    assert.ok(out.err.seen > out.err.limit || out.err.which === 'maxRounds', `${r.name}: the error says what was reached: ${out.err.message}`);
    assert.equal(out.failure, out.err, `${r.name}: the scheduler remembers the bound it reached`);
    assert.equal(out.again, out.err, `${r.name}: a flush made after the bound raises the same error again (a card that caught it cannot hide it)`);
  }
  // the error of a bound names the bound and the numbers, in words
  const e = new SchedulerBound('maxEventsPerFlush', 10, 11, 'x');
  assert.match(e.message, /scheduler bound reached: maxEventsPerFlush \(limit 10, reached 11\): x/);
  assert.equal(e.name, 'SchedulerBound');
  // and nothing of a runaway is left for the next test: no waiting work, no listeners, no bound
  assert.equal(sched.pending, 0);
  assert.equal(sched.failure, null);
  assert.equal(sched.stats.listeners, 0);
});

test('async net [r9] BOUNDED: after a bound has been reached every further scheduling call of a tracked caller throws the same error (so a card that catches it and goes on cannot keep allocating), and beginTest forgets it', async () => {
  await sched.withBounds({ maxWorkPerTest: 50 }, async () => {
    let first = null;
    for (let i = 0; i < 200 && first === null; i += 1) {
      try {
        queueMicrotask(() => {});
      } catch (e) {
        first = e;
      }
    }
    assert.ok(first instanceof SchedulerBound && first.which === 'maxWorkPerTest');
    for (const call of [() => setTimeout(() => {}, 10), () => setInterval(() => {}, 10), () => requestAnimationFrame(() => {}), () => requestIdleCallback(() => {}), () => Promise.resolve().then(() => {}), () => doc.createElement('i').addEventListener('x', () => {})]) {
      assert.throws(call, (err) => err === first);
    }
    assert.equal(sched.pending, 0, 'nothing was scheduled by the calls that threw');
  });
  assert.equal(sched.failure, null, 'withBounds ends with a fresh test');
  setTimeout(() => {}, 10);
  assert.equal(sched.pending, 1, 'and the scheduler works again');
  sched.clearAll();
});

test('[wall-clock] async net [r9] BOUNDED: the runaway cards are stopped quickly and the heap stays small (well under a second each, and under 300 MB in all; the suites run with a 3 GB heap and a guard at 5 GB, and neither is anywhere near)', async () => {
  const heap0 = heapMB();
  const t0 = performance.now();
  const times = [];
  for (const r of RUNAWAYS) {
    const t1 = performance.now();
    const out = await runRunaway(r);
    assert.ok(out.err instanceof SchedulerBound, r.name);
    times.push(performance.now() - t1);
    assert.ok(times.at(-1) < 1500, `${r.name}: ${times.at(-1).toFixed(0)} ms`);
  }
  assert.ok(performance.now() - t0 < 8000, `${(performance.now() - t0).toFixed(0)} ms for all of them`);
  assert.ok(heapMB() - heap0 < 300, `the heap grew by ${(heapMB() - heap0).toFixed(0)} MB`);
  console.log(`runaway cards: ${RUNAWAYS.length} stopped, the slowest in ${Math.max(...times).toFixed(0)} ms, the heap grew by ${(heapMB() - heap0).toFixed(0)} MB`);
});

// ---------------------------------------------------------------------------------------------------------------------------
// (4) INSPECT-SAFE NODES. When `assert.equal(node, null)` fails, Node builds the message by inspecting both values with a depth of 1000, no limit on arrays and custom inspection OFF. A node whose parent, document and
// listeners were enumerable properties was therefore walked together with the whole page: the (round 1) mutant AC6-strip-inside-production-body, which makes exactly that assertion fail, took the element and real-catalogue
// suites past 5 GB in two seconds on the first full run of the mutation proof of this round, and the memory guard killed them. The references that lead out of a node are not enumerable now (minidom.mjs: `quiet`).
// ---------------------------------------------------------------------------------------------------------------------------
test('minidom [r9] INSPECT-SAFE: a failing comparison of a node shows the node and nothing around it (tag and attributes, no parent, no document, no listeners), and the hazard is real (the same page with enumerable references makes a message hundreds of times larger)', () => {
  const p = page();
  for (let i = 0; i < 400; i += 1) {
    const d = doc.createElement('div');
    d.setAttribute('data-n', String(i));
    d.addEventListener('click', () => i);
    p.shell.appendChild(d);
  }
  const message = (a, b) => {
    try {
      assert.equal(a, b);
    } catch (e) {
      return String(e.message);
    }
    return '';
  };
  const small = message(p.strip, null);
  assert.ok(small.length > 0 && small.length < 3000, `${small.length} characters`);
  assert.doesNotMatch(small, /ownerDocument|childNodes|_listeners|parentNode|alert A01/);
  for (const n of [p.strip, p.shell, p.host, p.host.shadowRoot, p.shell.childNodes[3], doc.createTextNode('x'), doc, win]) assert.ok(message(n, null).length < 3000, `a failing comparison of ${n.tagName || n.constructor.name} is small`);
  // nothing was taken away: the references are still there to read and to write, and a node still has the same tree
  assert.equal(p.strip.parentNode, p.shell);
  assert.equal(p.shell.childNodes.length, 401);
  assert.equal(p.strip.ownerDocument, doc);
  assert.deepEqual(Object.keys(p.strip).filter((k) => ['parentNode', 'childNodes', 'ownerDocument', '_listeners', '_props', 'style'].includes(k)), []);
  const moved = doc.createElement('div');
  moved.parentNode = p.shell;
  assert.equal(moved.parentNode, p.shell, 'a quiet property can still be written');
  assert.deepEqual(Object.keys(moved).filter((k) => k === 'parentNode'), [], 'and stays quiet');
  // the control: the same page with the references enumerable again (what the stand-in was) is a message hundreds of times larger
  const loud = (n) => {
    for (const k of ['parentNode', 'childNodes', 'ownerDocument', '_listeners']) Object.defineProperty(n, k, { enumerable: true });
    for (const c of n.childNodes) if (c.nodeType === 1) loud(c);
  };
  const p2 = page();
  for (let i = 0; i < 400; i += 1) {
    const d = doc.createElement('div');
    d.setAttribute('data-n', String(i));
    p2.shell.appendChild(d);
  }
  loud(p2.shell);
  const big = message(p2.strip, null);
  assert.ok(big.length > 50 * small.length, `${big.length} characters against ${small.length}: the references made the message larger`);
  assert.ok(big.length < 60 * 1024 * 1024, 'and still small enough to be made here');
});
