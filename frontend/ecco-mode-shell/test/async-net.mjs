// The ASYNC NET (review round 9; not a test file). The owner's rule: a safety alert is visible in BOTH modes at ALL times. Until round 9 every strip test looked at the strip in the SAME task as the click or the
// hass update that caused the change, so a card that hid the strip a moment LATER (a promise, a microtask, a zero-delay timer, an animation frame, an observer callback, a listener) passed every test (reviewer
// mutants E05 and E08: the strip goes from 209 characters to 0 one tick after the switch and stays empty until the next update). This file is the net for that class. It has three parts, none of which asks
// "is this a known way to hide the strip":
//   1. the ENUMERATION of every place where the card can schedule or defer work (ASYNC_TOKENS, ALLOWED_ASYNC_SITES): the static pin in async.test.mjs fails on any occurrence that is not on the list, and the list
//      says WHY each one exists, so a new one is a decision a person takes, not an accident;
//   2. a SCHEDULER (installScheduler) that records every setTimeout, setInterval, requestAnimationFrame, requestIdleCallback, queueMicrotask, Promise.then, observer and event listener the card creates (with the
//      line of the card that did it) and that RUNS all of them, on demand, immediately and deterministically, in a bounded loop (flush). So a deferred hide, however it is reached (even by a computed name that no
//      reader of the source can follow), is executed by the test the moment it is asked to, with no real waiting;
//   3. a FINGERPRINT of the strip (stripFingerprint): its whole subtree and everything around it, in a form that two moments can be compared by. "Identical before and after the scheduled work ran" is the assertion.
// The tests are element.test.mjs (every AC6 test settles after each switch, hass update and timer step; the afterEach does it for every test) and async.test.mjs (the pin, the full tour, the negative controls).
//
// Review round 10 ([r10]) adds three more parts to the same net (the reviewer's survivors A04, A05 and A09: a hide that is gated on the CLOCK, and a hide inside the BODY of a continuation):
//   4. THE CLOCKS: the scheduler moves the card's own readings of performance.now() and Date.now() forward at every flush (a ratchet of one hour: time never goes back), so a hide that waits for a minute, an hour or a
//      day to pass cannot hide behind a frozen clock; every place the card reads a clock is recorded with its line, and a static pin (CLOCK_TOKENS, ALLOWED_CLOCK_SITES) lists the only places where the card may read a
//      clock or a page state (Date, performance, visibilityState, hidden, hasFocus ...): anything new fails until a person decides. The shift, the number of shifts and the number of reads each have a hard bound that throws.
//   5. THE BODIES: the bodies of the functions that the deferred work runs (attach, fail, say and the two they call) may use only the names on a documented list (CONTINUATION_BODIES): the strip, the shell, the Production
//      or Geek body and the host are not on it, so a continuation that touches them fails the pin until a person decides.
//   (The scheduler cannot move `new Date()` with no argument, because the card has none: the pin refuses a new one.)
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { CARD_PATH, tick } from './helpers.mjs';
import { MElement, MWindow, MEvent } from './minidom.mjs';

// ---------------------------------------------------------------------------------------------------------------------------
// 1. reading source: one entry per line, comments removed, the content of strings, templates and regular expressions blanked
// ---------------------------------------------------------------------------------------------------------------------------
const KEYWORDS = new Set(['const', 'let', 'var', 'return', 'typeof', 'in', 'of', 'case', 'new', 'else', 'do', 'void', 'delete', 'throw', 'yield', 'await', 'instanceof', 'export', 'default']);

/**
 * The source as a list of lines, each { plain, blank }: `plain` is the line with its comments removed, `blank` is `plain` with the CONTENT of every string, template text and regular expression removed
 * ('' , `` and /re/), so that a word inside a message ("and then ...") is not code. The line numbers are those of the file (a comment or a template that spans lines keeps its newlines).
 */
export function scanLines(src) {
  const lines = [];
  let plain = '';
  let blank = '';
  const put = (ch, b) => {
    if (ch === '\n') {
      lines.push({ plain, blank });
      plain = '';
      blank = '';
    } else {
      plain += ch;
      blank += b;
    }
  };
  const n = src.length;
  let i = 0;
  let prev = '';
  const regexAllowed = () => prev === '' || /^[(,=:[!&|?{};+\-*%<>~^]$/.test(prev) || KEYWORDS.has(prev);
  const stack = [{ type: 'code', braces: 0 }];
  while (i < n) {
    const ctx = stack[stack.length - 1];
    const c = src[i];
    if (ctx.type === 'text') {
      if (c === '\\') {
        put(c, '');
        if (i + 1 < n) put(src[i + 1], '');
        i += 2;
      } else if (c === '`') {
        put('`', '`');
        i += 1;
        stack.pop();
        prev = '`';
      } else if (c === '$' && src[i + 1] === '{') {
        put('$', '$');
        put('{', '{');
        i += 2;
        stack.push({ type: 'code', braces: 0 });
        prev = '{';
      } else {
        put(c, '');
        i += 1;
      }
      continue;
    }
    if (c === '/' && src[i + 1] === '/') {
      while (i < n && src[i] !== '\n') i += 1;
    } else if (c === '/' && src[i + 1] === '*') {
      const end = src.indexOf('*/', i + 2);
      const stop = end < 0 ? n : end + 2;
      for (let k = i; k < stop; k += 1) if (src[k] === '\n') put('\n', '\n');
      i = stop;
    } else if (c === "'" || c === '"') {
      put(c, c);
      i += 1;
      while (i < n && src[i] !== c && src[i] !== '\n') {
        if (src[i] === '\\') {
          put(src[i], '');
          i += 1;
          if (i < n && src[i] !== '\n') {
            put(src[i], '');
            i += 1;
          }
        } else {
          put(src[i], '');
          i += 1;
        }
      }
      if (i < n && src[i] === c) {
        put(c, c);
        i += 1;
      }
      prev = c;
    } else if (c === '`') {
      put('`', '`');
      i += 1;
      stack.push({ type: 'text' });
    } else if (c === '/' && regexAllowed()) {
      let j = i + 1;
      let inClass = false;
      while (j < n) {
        const d = src[j];
        if (d === '\\') j += 2;
        else if (d === '\n') break;
        else if (inClass) {
          if (d === ']') inClass = false;
          j += 1;
        } else if (d === '[') {
          inClass = true;
          j += 1;
        } else if (d === '/') break;
        else j += 1;
      }
      if (j < n && src[j] === '/') {
        j += 1;
        while (j < n && /[a-z]/.test(src[j])) j += 1;
        for (let k = i; k < j; k += 1) put(src[k], k === i ? '/re/' : '');
        i = j;
        prev = ')';
      } else {
        put(c, c);
        i += 1;
        prev = c;
      }
    } else if (/[A-Za-z_$]/.test(c)) {
      const m = /^[A-Za-z_$][\w$]*/.exec(src.slice(i, i + 80));
      for (const ch of m[0]) put(ch, ch);
      i += m[0].length;
      prev = KEYWORDS.has(m[0]) ? m[0] : 'a';
    } else if (/\d/.test(c)) {
      const m = /^[\w.]+/.exec(src.slice(i, i + 80));
      for (const ch of m[0]) put(ch, ch);
      i += m[0].length;
      prev = 'a';
    } else {
      if (c === '{') ctx.braces += 1;
      else if (c === '}') {
        if (ctx.braces === 0 && stack.length > 1) {
          put('}', '}');
          i += 1;
          stack.pop();
          prev = '}';
          continue;
        }
        ctx.braces -= 1;
      }
      put(c, c);
      i += 1;
      if (!/\s/.test(c)) prev = c;
    }
  }
  lines.push({ plain, blank });
  return lines;
}

/** The normal form of a line as a site key: comments gone, white space folded, trimmed. */
export const siteKey = (plainLine) => String(plainLine).replace(/\s+/g, ' ').trim();

// ---------------------------------------------------------------------------------------------------------------------------
// 2. the enumeration: every way a piece of work can be scheduled or deferred, and the only places where the card does it
// ---------------------------------------------------------------------------------------------------------------------------
/** What counts as a way to defer work. A token is matched on the blanked code (never inside a string or a comment), on every line of the card. */
export const ASYNC_TOKENS = Object.freeze({
  Promise: /\bPromise\b/,
  then: /\bthen\b/,
  catch: /\.\s*catch\s*\(/,
  finally: /\.\s*finally\s*\(/,
  async: /\basync\b/,
  await: /\bawait\b/,
  queueMicrotask: /\bqueueMicrotask\b/,
  setTimeout: /\bsetTimeout\b/,
  setInterval: /\bsetInterval\b/,
  setImmediate: /\bsetImmediate\b/,
  clearTimeout: /\bclearTimeout\b/,
  clearInterval: /\bclearInterval\b/,
  requestAnimationFrame: /\brequestAnimationFrame\b/,
  cancelAnimationFrame: /\bcancelAnimationFrame\b/,
  requestIdleCallback: /\brequestIdleCallback\b/,
  cancelIdleCallback: /\bcancelIdleCallback\b/,
  MutationObserver: /\bMutationObserver\b/,
  ResizeObserver: /\bResizeObserver\b/,
  IntersectionObserver: /\bIntersectionObserver\b/,
  PerformanceObserver: /\bPerformanceObserver\b/,
  MessageChannel: /\bMessageChannel\b/,
  nextTick: /\bnextTick\b/,
  scheduler: /\bscheduler\b/,
  Worker: /\bWorker\b/,
  Atomics: /\bAtomics\b/,
  AbortSignal: /\bAbortSignal\b/,
  addEventListener: /\baddEventListener\b/,
  removeEventListener: /\bremoveEventListener\b/,
  'on-property handler': /\.\s*on[a-z]{3,}\s*=(?!=)/,
});

/**
 * THE LIST. Each entry is one line of the card, as written (comments gone, white space folded), the token it holds, how many times that line may appear, where it is and why it exists. A site that is
 * not here fails the static pin until a person has read it and added it with a reason in the same commit (round 9: the pin is "anything new fails until a person decides"). The strings are the plain text of
 * the line, so a change to the line itself is also a decision.
 */
export const ALLOWED_ASYNC_SITES = Object.freeze([
  { token: 'addEventListener', line: 'const on = (el, type, fn) => el.addEventListener(type, fn);', count: 1, where: 'on()',
    why: 'the one helper every control of the card is wired with: the mode switch, the search box, the filters, the row, copy, export and open buttons. User events only; each handler runs in the task of the click.' },
  { token: 'addEventListener', line: "window.addEventListener('location-changed', this._onLocation);", count: 1, where: 'connectedCallback()',
    why: 'Home Assistant tells the page the path changed: the mode returns to Production (a reset, never a hide) when the card is left.' },
  { token: 'addEventListener', line: "window.addEventListener('pagehide', this._onPageHide);", count: 1, where: 'connectedCallback()',
    why: 'the page is being left or frozen: the mode returns to Production.' },
  { token: 'addEventListener', line: "if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {", count: 1, where: 'connectedCallback()', why: 'a feature test for the two window listeners below it: where there is no window the card registers nothing and schedules nothing.' },
  { token: 'removeEventListener', line: "if (typeof window !== 'undefined' && typeof window.removeEventListener === 'function') {", count: 1, where: '_unlisten()', why: 'a feature test for the two window listeners removed below it: the pair of the registration, on disconnect.' },
  { token: 'removeEventListener', line: "window.removeEventListener('location-changed', this._onLocation);", count: 1, where: '_unlisten()', why: 'the pair of the listener above, on disconnect.' },
  { token: 'removeEventListener', line: "window.removeEventListener('pagehide', this._onPageHide);", count: 1, where: '_unlisten()', why: 'the pair of the listener above, on disconnect.' },
  { token: 'ResizeObserver', line: "if (typeof ResizeObserver !== 'undefined') {", count: 1, where: 'connectedCallback()', why: 'a feature test for the observer below: where there is no ResizeObserver the card runs without the hidden-box reset, and nothing else changes.' },
  { token: 'ResizeObserver', line: 'this._ro = new ResizeObserver((entries) => {', count: 1, where: 'connectedCallback()',
    why: 'the only observer: when the card is shown in a 0 x 0 box (hidden by a tab or a dialog) the mode returns to Production. The callback only resets the mode; it touches no alert.' },
  { token: 'setInterval', line: 'this._timer = setInterval(() => this._onTimer(), ms);', count: 1, where: '_startTimer()',
    why: 'the one timer slot: the 15 s age tick and, after a burst of updates, one short flush. Both only re-run _refresh, which re-derives the strip from the same snapshot in both modes.' },
  { token: 'clearInterval', line: 'if (this._timer !== null) clearInterval(this._timer);', count: 1, where: '_stopTimer()', why: 'the pair of the interval above: the one timer slot is cleared on every restart and on disconnect, so no timer outlives the element.' },
  { token: 'then', line: "helpers().then((hp) => attach(hp.createCardElement(cfg))).catch((e) => fail(e && e.message ? e.message : 'unknown error'));", count: 1, where: '_mountChild()',
    why: 'Home Assistant card helpers build a child card asynchronously; the continuation attaches the child (or a notice) inside its own region. It never touches the strip.' },
  { token: 'catch', line: "helpers().then((hp) => attach(hp.createCardElement(cfg))).catch((e) => fail(e && e.message ? e.message : 'unknown error'));", count: 1, where: '_mountChild()',
    why: 'the failure branch of the same chain: a notice in the child\'s own wrapper.' },
  { token: 'then', line: "clip.writeText(text).then(() => say(`Copied ${what} (non-secret values only).`), () => say('The browser blocked the copy. Use the JSON or CSV button instead.'));", count: 1, where: '_copy()',
    why: 'the clipboard answers asynchronously; the continuation only writes one status line in the Geek surface.' },
]);

/** The occurrences of every token in the source: [{ token, line (1-based), key }]. (Review round 10: `tokens` can be another table, the clocks of CLOCK_TOKENS.) */
export function asyncOccurrences(src, tokens = ASYNC_TOKENS) {
  const out = [];
  scanLines(src).forEach((l, idx) => {
    for (const [token, re] of Object.entries(tokens)) if (re.test(l.blank)) out.push({ token, line: idx + 1, key: siteKey(l.plain) });
  });
  return out;
}

/** The pin: { unlisted: occurrences that are not on the list (or are more than the list allows), missing: list entries that are not found as often as they say }. */
export function asyncSiteProblems(src, allowed = ALLOWED_ASYNC_SITES, tokens = ASYNC_TOKENS) {
  const found = new Map();
  for (const o of asyncOccurrences(src, tokens)) {
    const k = `${o.token}\u0000${o.key}`;
    if (!found.has(k)) found.set(k, []);
    found.get(k).push(o);
  }
  const listed = new Map(allowed.map((a) => [`${a.token}\u0000${siteKey(a.line)}`, a]));
  const unlisted = [];
  const missing = [];
  for (const [k, occ] of found) {
    const a = listed.get(k);
    if (!a) unlisted.push(...occ.map((o) => `${o.token} at line ${o.line}: ${o.key}`));
    else if (occ.length > a.count) unlisted.push(...occ.slice(a.count).map((o) => `${o.token} at line ${o.line}: ${o.key} (listed ${a.count} time(s), found ${occ.length})`));
  }
  for (const [k, a] of listed) {
    const n = (found.get(k) || []).length;
    if (n < a.count) missing.push(`${a.token}: ${a.line} (listed ${a.count} time(s), found ${n})`);
  }
  return { unlisted, missing };
}

// ---------------------------------------------------------------------------------------------------------------------------
// 2b. [r10] THE CLOCKS: every place where the card reads a clock or a state of the page that a hide could be gated on
// ---------------------------------------------------------------------------------------------------------------------------
/**
 * What counts as a clock or a page-state gate. Reviewer mutants A04 and A05 (round 10) emptied the strip when the card's own clock, or performance.now(), was a minute (twenty seconds) past the moment the Geek surface
 * was built: both survived every suite, because every test kept the clock still. The class is "a hide that waits for something to change that the test never changes": time (Date, performance, a timestamp, the
 * card's own clock `_now`), visibility (visibilityState, document.hidden), focus (hasFocus), the connection (onLine) and a media query (matchMedia). A token is matched on the blanked code (never inside a string or a comment).
 */
export const CLOCK_TOKENS = Object.freeze({
  Date: /\bDate\b/,
  performance: /\bperformance\b/,
  Temporal: /\bTemporal\b/,
  hrtime: /\bhrtime\b/,
  getTime: /\bgetTime\b/,
  timeStamp: /\btimeStamp\b/,
  visibilityState: /\bvisibilityState\b/,
  'document.hidden': /\b(?:document|ownerDocument|doc)\s*\.\s*hidden\b/,
  hasFocus: /\bhasFocus\b/,
  onLine: /\bonLine\b/,
  matchMedia: /\bmatchMedia\b/,
  'the card clock': /\b_now\b/,
});

/**
 * THE LIST of the places where the card reads a clock (round 10). Each entry is one line of the card as written, the token it holds, how many times that line may appear, where it is and why it exists. The strings are
 * the plain text of the line, so a change to the line itself is also a decision. `new Date(ms)` with an argument is a conversion of a time that is already known (the clock is not read); the only readings of a clock are
 * Date.now() in the card's own clock (`_now`, which the tests replace) and performance.now() in the burst control.
 */
export const ALLOWED_CLOCK_SITES = Object.freeze([
  { token: 'Date', line: 'const t = Date.parse(v);', count: 1, where: 'the time reader', why: 'turns a timestamp TEXT that Home Assistant gave (last_updated, an attribute) into milliseconds: no clock is read, the same text always gives the same number.' },
  { token: 'Date', line: 'unit: r.unitText ? r.unitText : null, age_s: isNum(r.ageS) ? Math.round(r.ageS) : null, last_updated: isNum(r.lastUpdated) ? new Date(r.lastUpdated).toISOString() : null,', count: 1, where: 'exportRow()',
    why: 'writes the last update of a row (milliseconds already known) as text in the copy and the download: a conversion, not a clock.' },
  { token: 'Date', line: "const doc = { schema: EXPORT_SCHEMA, view_id: isStr(m.viewId) ? cleanText(m.viewId, 80) : '', generated_at: isNum(m.nowMs) ? new Date(m.nowMs).toISOString() : null,", count: 1, where: 'buildExport()',
    why: 'writes the time of the snapshot (milliseconds already known) as text in the copy and the download: a conversion, not a clock.' },
  { token: 'Date', line: 'this._now = () => Date.now();', count: 1, where: 'constructor()', why: 'THE card clock: the one place that reads the wall clock for the snapshot (ages, staleness). Tests replace it with a function they step.' },
  { token: 'the card clock', line: 'this._now = () => Date.now();', count: 1, where: 'constructor()', why: 'the definition of the card clock (above).' },
  { token: 'Date', line: "const t = typeof performance !== 'undefined' && typeof performance.now === 'function' ? performance.now() : Date.now();", count: 1, where: '_admit()',
    why: 'the burst control: how many rebuilds the last BURST_WINDOW_MS held. It reads the monotonic clock (or the wall clock where there is none) and decides ONLY whether a rebuild waits for the flush timer; it touches no alert.' },
  { token: 'performance', line: "const t = typeof performance !== 'undefined' && typeof performance.now === 'function' ? performance.now() : Date.now();", count: 1, where: '_admit()', why: 'the monotonic clock of the burst control (above).' },
  { token: 'Date', line: 'return new Intl.DateTimeFormat(lang, { dateStyle: \'short\', timeStyle: \'medium\' }).format(new Date(ms));', count: 1, where: '_fmtTime()', why: 'writes a time already known (the snapshot time) for the Geek header, in the language of Home Assistant: a conversion, not a clock.' },
  { token: 'Date', line: 'return new Date(ms).toISOString();', count: 1, where: '_fmtTime()', why: 'the fallback of the line above where Intl is not available: a conversion, not a clock.' },
  { token: 'the card clock', line: 'const now = this._now();', count: 1, where: '_refresh()', why: 'the ONE read of the card clock per rebuild: every age, every status and the burst window of the snapshot come from it.' },
  { token: 'Date', line: "const stamp = new Date(snap ? snap.nowMs : this._now()).toISOString().slice(0, 19).replace(/[-:]/g, '').replace('T', '-');", count: 1, where: '_download()',
    why: 'the time in the name of a downloaded file: the snapshot time (or the card clock when there is none yet): a conversion plus one read of the card clock.' },
  { token: 'the card clock', line: "const stamp = new Date(snap ? snap.nowMs : this._now()).toISOString().slice(0, 19).replace(/[-:]/g, '').replace('T', '-');", count: 1, where: '_download()', why: 'the read of the card clock for the file name (above).' },
]);

/** The pin of the clocks, in the same form as the pin of the deferrals: { unlisted, missing }. */
export const clockSiteProblems = (src, allowed = ALLOWED_CLOCK_SITES) => asyncSiteProblems(src, allowed, CLOCK_TOKENS);
export const clockOccurrences = (src) => asyncOccurrences(src, CLOCK_TOKENS);

// ---------------------------------------------------------------------------------------------------------------------------
// 2c. [r10] THE BODIES of the functions that deferred work runs
// ---------------------------------------------------------------------------------------------------------------------------
/**
 * The functions that a continuation (the card helpers' promise, its rejection, the clipboard's promise) reaches: the body of each may use only the names listed here, as a variable or as a member. The alert strip, the
 * shell, `ui`, the host, the shadow root, a selector, a parent and the renderer of the strip are NOT names on any list, so a continuation that touches the strip (reviewer mutant A09, and its variants in fail and say)
 * is refused by the pin until a person adds the name and the reason. `header` is the line the body starts at (found exactly once); the body ends where its braces close.
 */
export const CONTINUATION_BODIES = Object.freeze([
  { name: 'attach', header: 'const attach = (el) => {', where: '_mountChild()', vocabulary: ['attach', 'el', 'gen', 'this', '_gen', 'wrap', 'appendChild', '_kids', 'push', '_hass', 'null', 'undefined', 'hass'],
    why: 'runs when Home Assistant has built a child card: it puts the child into ITS OWN wrapper (wrap), remembers it to feed it hass, and gives it the current hass. It never reaches the strip, the shell or a mode.' },
  { name: 'fail', header: 'const fail = (message) => {', where: '_mountChild()', vocabulary: ['fail', 'message', 'gen', 'this', '_gen', 'wrap', 'appendChild', '_notice'],
    why: 'runs when a child card could not be made (also from the rejection of the helpers promise): it adds one notice to the child\'s own wrapper. It never reaches the strip, the shell or a mode.' },
  { name: '_notice', header: '_notice(flag, text) {', where: 'EccoModeShell', vocabulary: ['_notice', 'flag', 'text', 'doc', 'this', 'ownerDocument', 'mk', 'class', 'role', 'cleanText'],
    why: 'builds the text node of a notice (the one thing fail makes). It returns a node and touches nothing else.' },
  { name: 'say', header: 'const say = (m) => {', where: '_copy()', vocabulary: ['say', 'm', 'this', '_geek'],
    why: 'runs when the clipboard answers (or at once where there is no clipboard): it hands one status line to the Geek surface, if there is one. It never reaches the strip, the shell or a mode.' },
  { name: 'GeekSurface.say', header: 'say(text) {', where: 'GeekSurface', vocabulary: ['say', 'text', 'this', 'ui', 'status_line', 'textContent'],
    why: 'writes one status line inside the Geek surface\'s own list of nodes (this.ui is the surface\'s own, not the shell\'s).' },
]);
const KEYWORDS_IGNORED = new Set(['const', 'let', 'var', 'return', 'if', 'else']);
const BODY_LINES_MAX = 40; // a body of more than 40 lines is not one of these (and the search for its end stops there)

/** The problems of the bodies: a header not found exactly once, a body that does not close, a name that is not on the list. */
export function continuationProblems(src, specs = CONTINUATION_BODIES) {
  const lines = scanLines(src);
  const problems = [];
  for (const spec of specs) {
    const at = [];
    lines.forEach((l, i) => {
      if (siteKey(l.plain) === siteKey(spec.header)) at.push(i);
    });
    if (at.length !== 1) {
      problems.push(`${spec.name}: the header line "${spec.header}" is found ${at.length} times (exactly once is required)`);
      continue;
    }
    let depth = 0;
    let started = false;
    let end = -1;
    for (let i = at[0]; i < lines.length && i < at[0] + BODY_LINES_MAX; i += 1) {
      for (const ch of lines[i].blank) {
        if (ch === '{') {
          depth += 1;
          started = true;
        } else if (ch === '}') depth -= 1;
      }
      if (started && depth <= 0) {
        end = i;
        break;
      }
    }
    if (end < 0) {
      problems.push(`${spec.name}: the body does not close within ${BODY_LINES_MAX} lines`);
      continue;
    }
    const allowed = new Set(spec.vocabulary);
    const text = lines.slice(at[0], end + 1).map((l) => l.blank).join('\n');
    const bad = new Set();
    for (const m of text.matchAll(/[A-Za-z_][\w$]*|\$[\w$]+/g)) if (!KEYWORDS_IGNORED.has(m[0]) && !allowed.has(m[0])) bad.add(m[0]);
    for (const w of bad) problems.push(`${spec.name}: the name "${w}" is not on its list (${[...allowed].join(', ')})`);
  }
  return problems;
}

// ---------------------------------------------------------------------------------------------------------------------------
// 3. the scheduler (BOUNDED: it cannot run away)
// ---------------------------------------------------------------------------------------------------------------------------
/**
 * THE BOUNDS. The first version of this scheduler had none, and a card session that fired one event of every kind it listens for filled a 2 GB heap in seconds (the PC ran out of virtual memory twice): every fired
 * click re-rendered a part of the Geek surface, every re-render registered new listeners, the next flush fired those too, and so on without end. A net that can eat the machine is worse than no net, so every kind of work
 * the scheduler records, runs or fires has a hard maximum, and when one is reached the scheduler THROWS (SchedulerBound, naming the bound and the numbers) in well under a second, and from then on every further call
 * of the card that schedules anything throws the same error until beginTest(), so a card that catches the exception and goes on cannot keep allocating. The numbers are about ten times what the real tour needs
 * (async.test.mjs prints what it uses; the tour of element.test.mjs asserts that it stays under a quarter of each bound).
 */
export const BOUNDS = Object.freeze({
  maxRecords: 4000, // DIFFERENT places (an API and a line of the card) that the scheduler remembers, per test: the same place seen again is only counted
  maxListeners: 4000, // listener registrations held at one time (when the limit is reached, those on elements that have left the page are dropped first, because they can never be fired; what is still over the limit is alive, and is a runaway)
  maxPending: 500, // timers, animation frames and idle callbacks waiting at one time
  maxCallbacksPerFlush: 1000, // timers, frames, idle callbacks and observer callbacks that ONE flush runs
  maxEventsPerFlush: 2000, // events that ONE flush fires
  maxRounds: 6, // rounds of one flush: a card whose timers still wait after the last round does not settle
  maxWorkPerTest: 200000, // everything above added up (a record, a registration, a callback, an event, a flush), per test
  // review round 10: the clocks the card sees (performance.now and Date.now) are moved forward at every flush; each of these throws when it is reached
  maxClockStepMs: 86400000, // the largest step ONE flush may move the clocks (a day); a larger or a negative or a non-numeric one throws
  maxClockShiftMs: 7200000000, // the largest total the clocks may have been moved in one test (2000 hours)
  maxClockReads: 200000, // readings of a clock by the card (or, in the scope of a test of the scheduler, by its caller) in one test: a card that reads the clock in a loop is stopped
});
/** How far one flush moves the clocks the card sees, unless the flush says otherwise: an hour (time only goes forward). */
export const CLOCK_STEP_MS = 3600000;

/** The error of a bound that was reached. `which` is the name of the bound, `seen` the number that was reached, `limit` the bound. */
export class SchedulerBound extends Error {
  constructor(which, limit, seen, detail = '') {
    super(`scheduler bound reached: ${which} (limit ${limit}, reached ${seen})${detail ? `: ${detail}` : ''}. A card that keeps scheduling work in its own handlers does not settle; the flush stops here instead of running away.`);
    this.name = 'SchedulerBound';
    this.which = which;
    this.limit = limit;
    this.seen = seen;
  }
}

const FRAME = /(file:\/\/\/[^\s)]*?)(?:\?[^:\s)]*)?:(\d+):(\d+)/;
const samePath = (a, b) => path.resolve(a).toLowerCase() === path.resolve(b).toLowerCase();
const THIS_FILE = fileURLToPath(import.meta.url);
const TEST_DIR = path.dirname(THIS_FILE);
const inside = (dir, file) => {
  const rel = path.relative(dir, file);
  return rel !== '' && !rel.startsWith('..') && !path.isAbsolute(rel);
};

/**
 * Install the scheduler (once per test process, BEFORE the card module is evaluated, so that a reference taken at import time is the recorded one). Every API below still works as it did (the timers are real,
 * the promises are real), and every call made while the card is on the stack is recorded with the card's own line. flush() then runs what is pending. Returns the scheduler; uninstall() puts everything back.
 *   resizeObservers: the ResizeObserver instances the test file already collects (installResizeObserver in minidom.mjs); they are fired with a normal box.
 *   bounds: overrides of BOUNDS (a test of the bounds themselves makes them small).
 * Which calls are the scheduler's business: those made by the card, and those made by the test files (the DEFERRALS of async.test.mjs, the waits of element.test.mjs). A timer that only Node's own test runner
 * made is left alone: not recorded, never run early.
 */
export function installScheduler({ resizeObservers = [], cardFile = CARD_PATH, bounds: boundsOverride = {}, clockScope: clockScopeDefault = 'card' } = {}) {
  if (clockScopeDefault !== 'card' && clockScopeDefault !== 'tracked') throw new RangeError(`clockScope is 'card' or 'tracked', not ${String(clockScopeDefault)}`);
  const source = readFileSync(cardFile, 'utf8');
  const lines = scanLines(source);
  let bounds = { ...BOUNDS, ...boundsOverride };
  const real = {
    setTimeout: globalThis.setTimeout, clearTimeout: globalThis.clearTimeout, setInterval: globalThis.setInterval, clearInterval: globalThis.clearInterval,
    queueMicrotask: globalThis.queueMicrotask, then: Promise.prototype.then,
    raf: globalThis.requestAnimationFrame, caf: globalThis.cancelAnimationFrame, ric: globalThis.requestIdleCallback, cic: globalThis.cancelIdleCallback,
    MutationObserver: globalThis.MutationObserver, IntersectionObserver: globalThis.IntersectionObserver, ResizeObserver: globalThis.ResizeObserver,
    elAdd: MElement.prototype.addEventListener, winAdd: MWindow.prototype.addEventListener,
  };
  const records = []; // one per site: { api, line, key, count, ... }
  const recordAt = new Map();
  const peak = { work: 0, listeners: 0, alive: 0, records: 0, pending: 0, callbacksPerFlush: 0, eventsPerFlush: 0, clockShiftMs: 0, clockReads: 0, clockSteps: 0 }; // the largest each number has been in any test so far (a calibration, printed by the tests)
  const timers = new Map(); // handle -> { kind, fn, args, ms }
  const frames = new Map();
  const idles = new Map();
  const listeners = new Map(); // target -> Set of event types (every registration, by whoever makes it; the pair is what flush({ events }) fires)
  let pairs = 0;
  const observers = { MutationObserver: [], IntersectionObserver: [], ResizeObserver: resizeObservers };
  let nextId = 1;
  let work = 0;
  let failure = null;

  // ---- the bounds
  const bound = (which, seen, detail = '') => {
    if (failure === null) failure = new SchedulerBound(which, bounds[which], seen, detail);
    throw failure;
  };
  /** Add `n` units of work; the total per test is bounded. Once a bound has been reached everything that charges throws again. */
  const charge = (n = 1) => {
    if (failure !== null) throw failure;
    work += n;
    if (work > peak.work) peak.work = work;
    if (work > bounds.maxWorkPerTest) bound('maxWorkPerTest', work);
  };

  /** The line of the card that is on the stack (null when the card is not), and whether a test file (not this one) is. */
  const callerOf = (stack) => {
    let line = null;
    let test = false;
    for (const row of String(stack).split('\n').slice(1)) {
      const m = FRAME.exec(row);
      if (!m) continue;
      let file;
      try {
        file = fileURLToPath(m[1]);
      } catch {
        continue;
      }
      if (samePath(file, THIS_FILE)) continue;
      if (line === null && samePath(file, cardFile)) line = Number(m[2]);
      else if (inside(TEST_DIR, file)) test = true;
    }
    return { line, tracked: line !== null || test };
  };
  const whoCalls = () => {
    const limit = Error.stackTraceLimit;
    Error.stackTraceLimit = 12;
    const stack = new Error('stack').stack;
    Error.stackTraceLimit = limit;
    return callerOf(stack);
  };
  /** A call to a scheduling API: the card's own are recorded (and bounded), a test file's are charged, Node's own are ignored. Returns whether it is tracked. */
  const record = (api, extra = {}) => {
    if (failure !== null) {
      const who = whoCalls();
      if (who.tracked) throw failure;
      return false;
    }
    const who = whoCalls();
    if (!who.tracked) return false;
    charge(1);
    if (who.line === null) return true;
    // one record per SITE (the API and the line of the card): a card that registers 600 listeners from one line is one site seen 600 times, so the records cannot grow with the volume, only with the number of different places
    const at = `${api}\u0000${who.line}`;
    const seen = recordAt.get(at);
    if (seen) {
      seen.count += 1;
      return true;
    }
    if (records.length >= bounds.maxRecords) bound('maxRecords', records.length + 1, api);
    const rec = { api, line: who.line, key: lines[who.line - 1] ? siteKey(lines[who.line - 1].plain) : '?', count: 1, ...extra };
    records.push(rec);
    recordAt.set(at, rec);
    if (records.length > peak.records) peak.records = records.length;
    return true;
  };

  // ---- the registry of listeners: only those that can still be fired are kept
  /** An element can be fired at while it is in a shadow root or the document, or is a card host (it has a shadow root of its own); a window always can. */
  const isLive = (t) => {
    if (!(t instanceof MElement)) return true;
    if (t.isConnected) return true;
    const top = t.getRootNode();
    return top === t && t.shadowRoot !== undefined && t.shadowRoot !== null;
  };
  const prune = () => {
    for (const [t, types] of listeners) {
      if (!isLive(t)) {
        pairs -= types.size;
        listeners.delete(t);
      }
    }
  };
  const remember = (target, type) => {
    let types = listeners.get(target);
    if (!types) {
      types = new Set();
      listeners.set(target, types);
    }
    if (!types.has(type)) {
      types.add(type);
      pairs += 1;
      if (pairs > bounds.maxListeners) {
        prune(); // the ones that were on elements that have since left the page are no longer counted: what is left is what is alive
        if (pairs > bounds.maxListeners) bound('maxListeners', pairs, `${type} on ${target.tagName || 'the window'}`);
      }
      if (pairs > peak.listeners) peak.listeners = pairs;
    }
  };
  const livePairs = () => {
    prune();
    const out = [];
    for (const [t, types] of listeners) for (const type of types) out.push([t, type]);
    if (out.length > peak.alive) peak.alive = out.length;
    return out;
  };
  const checkPending = () => {
    const n = timers.size + frames.size + idles.size;
    if (n > peak.pending) peak.pending = n;
    if (n > bounds.maxPending) bound('maxPending', n);
  };

  globalThis.setTimeout = function setTimeout(fn, ms, ...args) {
    if (typeof fn !== 'function' || !record('setTimeout', { ms: Number(ms) || 0 })) return real.setTimeout.call(this, fn, ms, ...args);
    const h = real.setTimeout.call(this, () => {
      timers.delete(h);
      return fn(...args);
    }, ms);
    timers.set(h, { kind: 'timeout', fn, args, ms });
    checkPending();
    return h;
  };
  globalThis.setInterval = function setInterval(fn, ms, ...args) {
    if (typeof fn !== 'function' || !record('setInterval', { ms: Number(ms) || 0 })) return real.setInterval.call(this, fn, ms, ...args);
    const h = real.setInterval.call(this, fn, ms, ...args);
    timers.set(h, { kind: 'interval', fn, args, ms });
    checkPending();
    return h;
  };
  globalThis.clearTimeout = function clearTimeout(h) {
    timers.delete(h);
    return real.clearTimeout.call(this, h);
  };
  globalThis.clearInterval = function clearInterval(h) {
    timers.delete(h);
    return real.clearInterval.call(this, h);
  };
  globalThis.queueMicrotask = function queueMicrotask(fn) {
    record('queueMicrotask');
    return real.queueMicrotask.call(this, fn);
  };
  Promise.prototype.then = function then(onFulfilled, onRejected) {
    record('then');
    return real.then.call(this, onFulfilled, onRejected);
  };
  // the browser APIs Node does not have: present, so that code that asks `typeof X` before using them is no longer dormant in the tests
  globalThis.requestAnimationFrame = function requestAnimationFrame(cb) {
    record('requestAnimationFrame');
    const id = nextId;
    nextId += 1;
    frames.set(id, cb);
    checkPending();
    return id;
  };
  globalThis.cancelAnimationFrame = function cancelAnimationFrame(id) {
    frames.delete(id);
  };
  globalThis.requestIdleCallback = function requestIdleCallback(cb) {
    record('requestIdleCallback');
    const id = nextId;
    nextId += 1;
    idles.set(id, cb);
    checkPending();
    return id;
  };
  globalThis.cancelIdleCallback = function cancelIdleCallback(id) {
    idles.delete(id);
  };
  const makeObserver = (name) => class {
    constructor(cb) {
      this.cb = cb;
      this.targets = [];
      this.disconnected = false;
      record(name);
      if (observers[name].length >= bounds.maxListeners) bound('maxListeners', observers[name].length + 1, name);
      observers[name].push(this);
    }

    observe(t) {
      this.targets.push(t);
    }

    unobserve() {}

    disconnect() {
      this.disconnected = true;
    }

    takeRecords() {
      return [];
    }
  };
  if (real.MutationObserver === undefined) globalThis.MutationObserver = makeObserver('MutationObserver');
  if (real.IntersectionObserver === undefined) globalThis.IntersectionObserver = makeObserver('IntersectionObserver');
  if (real.ResizeObserver !== undefined) {
    const Base = real.ResizeObserver;
    globalThis.ResizeObserver = class extends Base {
      constructor(cb) {
        super(cb);
        record('ResizeObserver');
      }
    };
  }
  // every listener is remembered (by whoever registers it), so that flush({ events: true }) can fire one event of each kind at its target; only the card's own are in `records`
  MElement.prototype.addEventListener = function addEventListener(type, fn) {
    record('addEventListener', { type: String(type) });
    remember(this, String(type));
    return real.elAdd.call(this, type, fn);
  };
  MWindow.prototype.addEventListener = function addEventListener(type, fn) {
    record('addEventListener', { type: String(type) });
    remember(this, String(type));
    return real.winAdd.call(this, type, fn);
  };

  // ---- the clocks (review round 10). The card reads performance.now() (the burst control) and Date.now() (its own clock, which the tests replace). Reviewer mutants A04 and A05 emptied the strip when a clock was
  // a minute (twenty seconds) past the moment the Geek surface was built, and survived because no test ever moved a clock. Now every reading of a clock BY THE CARD is recorded (with its line of the card: the dynamic
  // half of the pin of the clocks), and is moved forward by `clockShift`, which every flush raises by a step (an hour): time only goes forward, so a hide that waits for a minute, an hour or a day to pass is
  // triggered by the first flush after it was armed. Test code and Node's own code read the real clocks (a test that measures how long something took is not disturbed). `scope: 'tracked'` also moves the readings of the
  // test files (for the tests of the scheduler itself, whose synthetic cards live in a test file).
  const realClock = { perfDesc: Object.getOwnPropertyDescriptor(performance, 'now'), perfNow: performance.now, dateNow: Date.now };
  let clockShift = 0;
  let clockReads = 0;
  let clockSteps = 0;
  let clockScope = clockScopeDefault;
  const clockRecords = [];
  const clockAt = new Map();
  const readClock = (api, real, self) => {
    const raw = real.call(self);
    const who = whoCalls();
    const mine = clockScope === 'tracked' ? who.tracked : who.line !== null;
    if (!mine) return raw;
    if (failure !== null) throw failure;
    clockReads += 1;
    if (clockReads > peak.clockReads) peak.clockReads = clockReads;
    if (clockReads > bounds.maxClockReads) bound('maxClockReads', clockReads, api);
    if (who.line !== null) {
      const at = `${api}\u0000${who.line}`;
      const seen = clockAt.get(at);
      if (seen) seen.count += 1;
      else {
        if (clockRecords.length >= bounds.maxRecords) bound('maxRecords', clockRecords.length + 1, api);
        const rec = { api, line: who.line, key: lines[who.line - 1] ? siteKey(lines[who.line - 1].plain) : '?', count: 1 };
        clockRecords.push(rec);
        clockAt.set(at, rec);
      }
    }
    return raw + clockShift;
  };
  performance.now = function now() {
    return readClock('performance.now', realClock.perfNow, this);
  };
  Date.now = function now() {
    return readClock('Date.now', realClock.dateNow, this);
  };
  /** Move the clocks the card sees forward by `stepMs` (a bounded, finite, non-negative number; the total is bounded too). */
  const stepClock = (stepMs) => {
    if (failure !== null) throw failure;
    if (typeof stepMs !== 'number' || !Number.isFinite(stepMs) || stepMs < 0) bound('maxClockStepMs', stepMs, 'a clock step must be a finite number of milliseconds, zero or more');
    if (stepMs > bounds.maxClockStepMs) bound('maxClockStepMs', stepMs);
    if (clockShift + stepMs > bounds.maxClockShiftMs) bound('maxClockShiftMs', clockShift + stepMs);
    clockShift += stepMs;
    clockSteps += 1;
    if (clockShift > peak.clockShiftMs) peak.clockShiftMs = clockShift;
    if (clockSteps > peak.clockSteps) peak.clockSteps = clockSteps;
  };

  // a browser's window HAS these (window.setTimeout is setTimeout): the stand-in window gets the same recording functions, so a card that reaches them through the window, by a name built at run time, is recorded and run too
  const WINDOW_NAMES = ['setTimeout', 'clearTimeout', 'setInterval', 'clearInterval', 'queueMicrotask', 'requestAnimationFrame', 'cancelAnimationFrame', 'requestIdleCallback', 'cancelIdleCallback'];
  const win = globalThis.window;
  const winSaved = new Map();
  if (win) {
    for (const n of WINDOW_NAMES) {
      winSaved.set(n, Object.getOwnPropertyDescriptor(win, n));
      win[n] = globalThis[n];
    }
  }
  const restore = (name, value) => {
    if (value === undefined) delete globalThis[name];
    else globalThis[name] = value;
  };
  const sched = {
    records,
    /** The numbers the scheduler is bounding, now (a test prints them, and the tour asserts that it stays under a fraction of each bound). */
    get stats() {
      return { work, records: records.length, listeners: pairs, pending: timers.size + frames.size + idles.size, clockShiftMs: clockShift, clockReads, clockSteps, bounds: { ...bounds } };
    },
    /** The largest each of the bounded numbers has been in any test so far. */
    get peak() {
      return { ...peak };
    },
    /** The number of timers, animation frames and idle callbacks that are waiting. */
    get pending() {
      return timers.size + frames.size + idles.size;
    },
    /** The bound that was reached in this test, or null. A flush raises it again, so a card that caught the error in its own handler cannot hide it. */
    get failure() {
      return failure;
    },
    /** The clocks the card sees: how far they have been moved (milliseconds), how many times, and how often the card read one, in this test. */
    get clock() {
      return { shiftMs: clockShift, steps: clockSteps, reads: clockReads, scope: clockScope };
    },
    /** The places (API and line of the card) where the card read a clock in this test: [{ api, line, key, count }]. */
    clockSites(api = null) {
      return clockRecords.filter((r) => api === null || r.api === api);
    },
    /** Run `fn` with the clocks of other callers moved as well ('tracked': the test files too) or only the card's ('card'), then put the scope back. */
    withClockScope(scope, fn) {
      if (scope !== 'card' && scope !== 'tracked') throw new RangeError(`clockScope is 'card' or 'tracked', not ${String(scope)}`);
      const old = clockScope;
      clockScope = scope;
      try {
        return fn();
      } finally {
        clockScope = old;
      }
    },
    /** Raise the bound that was reached, if any. */
    check() {
      if (failure !== null) throw failure;
    },
    /** Cancel every timer, interval, animation frame and idle callback that is waiting (a test that made some of its own, and does not want them to run later). */
    clearAll() {
      for (const h of [...timers.keys()]) {
        real.clearTimeout(h);
        real.clearInterval(h);
      }
      timers.clear();
      frames.clear();
      idles.clear();
    },
    /** Forget the listeners registered so far (a test that fires events starts from its own elements, not from every element of the earlier tests). */
    resetListeners() {
      listeners.clear();
      pairs = 0;
    },
    /** The start of a test: the work counter, the records, the registry and the waiting work are those of this test only, and a bound reached by the one before is forgotten (its test has reported it). */
    beginTest() {
      work = 0;
      failure = null;
      records.length = 0;
      recordAt.clear();
      clockShift = 0;
      clockReads = 0;
      clockSteps = 0;
      clockScope = clockScopeDefault;
      clockRecords.length = 0;
      clockAt.clear();
      sched.resetListeners();
      sched.clearAll();
    },
    /** Run `fn` (async) with other bounds, then put the old ones back: for the tests of the bounds themselves. The bounds that `fn` reached are forgotten afterwards, with everything it left waiting. */
    async withBounds(overrides, fn, { clockScope: scope = null } = {}) {
      const old = bounds;
      bounds = { ...bounds, ...overrides };
      if (scope !== null) {
        if (scope !== 'card' && scope !== 'tracked') throw new RangeError(`clockScope is 'card' or 'tracked', not ${String(scope)}`);
        clockScope = scope;
      }
      try {
        return await fn();
      } finally {
        bounds = old;
        sched.beginTest();
      }
    },
    /** The recorded calls of one API (or all), as the card lines that made them. */
    sites(api = null) {
      return records.filter((r) => api === null || r.api === api);
    },
    /**
     * Run everything that is waiting, now, in a bounded loop, and then let the promises settle: the macrotask (setImmediate, which also runs every microtask and every promise continuation queued before it),
     * every timeout (whatever its delay: a hide scheduled for twenty seconds runs too), every interval once, every animation frame and idle callback, every observer callback (a normal box for the resize observer,
     * a change of children for a mutation observer, both an intersecting and a non-intersecting entry for an intersection observer) and, with `events`, one event of every kind the card listens for, on the
     * element it listens on. The listeners that exist when the flush STARTS are the ones it fires, each pair once, and only while its element is still on the page: what the events register is not fired by this flush.
     * `after(what)` is called after each step, so a test can assert its invariant (the strip) after EVERY step, not only at the end.
     * It throws SchedulerBound (and does not loop) when a bound is reached or when timers, frames or idle callbacks still wait after the last round (the card keeps re-arming them).
     */
    async flush({ rounds = bounds.maxRounds, events = false, after = null, clockStepMs = CLOCK_STEP_MS } = {}) {
      sched.check();
      charge(1);
      stepClock(clockStepMs);
      const step = (what) => {
        if (after) after(what);
      };
      let ran = 0;
      let callbacks = 0;
      const callback = () => {
        callbacks += 1;
        ran += 1;
        charge(1);
        if (callbacks > peak.callbacksPerFlush) peak.callbacksPerFlush = callbacks;
        if (callbacks > bounds.maxCallbacksPerFlush) bound('maxCallbacksPerFlush', callbacks);
      };
      const toFire = events ? livePairs() : [];
      if (toFire.length > bounds.maxEventsPerFlush) bound('maxEventsPerFlush', toFire.length, 'listeners to fire at');
      const rounded = Math.min(rounds, bounds.maxRounds);
      let waiting = false;
      for (let r = 0; r < rounded; r += 1) {
        await tick();
        sched.check();
        step('a macrotask and every microtask before it');
        const batch = [...timers.entries()].filter(([, t]) => t.kind === 'timeout' || r === 0);
        const fr = [...frames.entries()];
        const id = [...idles.entries()];
        frames.clear();
        idles.clear();
        for (const [h, t] of batch) {
          if (!timers.has(h)) continue;
          if (t.kind === 'timeout') {
            timers.delete(h);
            real.clearTimeout(h);
          }
          callback();
          t.fn(...t.args);
          step(`a ${t.kind} of ${t.ms} ms`);
          await tick();
          sched.check();
        }
        for (const [, cb] of fr) {
          callback();
          cb(performance.now());
          step('an animation frame');
        }
        for (const [, cb] of id) {
          callback();
          cb({ didTimeout: false, timeRemaining: () => 40 });
          step('an idle callback');
        }
        if (r === 0) {
          for (const o of [...observers.ResizeObserver]) {
            if (o.disconnected || typeof o.fire !== 'function') continue;
            callback();
            o.fire(400, 300);
            step('a resize observer callback');
          }
          for (const o of [...observers.MutationObserver]) {
            if (o.disconnected) continue;
            callback();
            for (const t of o.targets) o.cb([{ type: 'childList', target: t, addedNodes: [], removedNodes: [] }], o);
            step('a mutation observer callback');
          }
          for (const o of [...observers.IntersectionObserver]) {
            if (o.disconnected) continue;
            callback();
            for (const visible of [false, true]) o.cb(o.targets.map((target) => ({ target, isIntersecting: visible, intersectionRatio: visible ? 1 : 0 })), o);
            step('an intersection observer callback');
          }
          let fired = 0;
          for (const [target, type] of toFire) {
            if (!isLive(target)) continue;
            fired += 1;
            if (fired > peak.eventsPerFlush) peak.eventsPerFlush = fired;
            if (fired > bounds.maxEventsPerFlush) bound('maxEventsPerFlush', fired);
            charge(1);
            ran += 1;
            target.dispatchEvent(new MEvent(type));
            step(`a ${type} event on ${target.tagName || 'the window'}`);
          }
        }
        await tick();
        sched.check();
        waiting = [...timers.values()].some((t) => t.kind === 'timeout') || frames.size > 0 || idles.size > 0;
        if (!waiting) break;
      }
      if (waiting) bound('maxRounds', rounded, `${[...timers.values()].filter((t) => t.kind === 'timeout').length} timers, ${frames.size} animation frames and ${idles.size} idle callbacks still wait: the card keeps re-arming them`);
      await tick();
      sched.check();
      step('the end of the flush');
      return ran;
    },
    uninstall() {
      restore('setTimeout', real.setTimeout);
      restore('clearTimeout', real.clearTimeout);
      restore('setInterval', real.setInterval);
      restore('clearInterval', real.clearInterval);
      restore('queueMicrotask', real.queueMicrotask);
      Promise.prototype.then = real.then;
      restore('requestAnimationFrame', real.raf);
      restore('cancelAnimationFrame', real.caf);
      restore('requestIdleCallback', real.ric);
      restore('cancelIdleCallback', real.cic);
      restore('MutationObserver', real.MutationObserver);
      restore('IntersectionObserver', real.IntersectionObserver);
      restore('ResizeObserver', real.ResizeObserver);
      MElement.prototype.addEventListener = real.elAdd;
      MWindow.prototype.addEventListener = real.winAdd;
      Date.now = realClock.dateNow;
      if (realClock.perfDesc) Object.defineProperty(performance, 'now', realClock.perfDesc);
      else delete performance.now;
      if (win) {
        for (const [n, d] of winSaved) {
          if (d) Object.defineProperty(win, n, d);
          else delete win[n];
        }
      }
      sched.clearAll();
    },
  };
  return sched;
}

// ---------------------------------------------------------------------------------------------------------------------------
// 4. the fingerprint of the strip
// ---------------------------------------------------------------------------------------------------------------------------
const attrsOf = (n, skip = []) => [...n.attrs].filter(([k]) => !skip.includes(k)).sort(([a], [b]) => (a < b ? -1 : 1)).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(' ');
const serialise = (n) => (n.nodeType === 3 ? JSON.stringify(n.data) : `<${n.tagName} ${attrsOf(n)}>${n.childNodes.map(serialise).join('')}</${n.tagName}>`);

/**
 * Everything that makes the strip what a person sees and hears, as one string: its whole subtree (tags, attributes, text), then every ancestor up to the host with its own attributes (hidden, inert, aria-hidden,
 * role ... anything; only the mode and the theme are left out, because those change on purpose), and the elements before the strip in its shell (what pushes it down). Two moments are the same strip when their
 * fingerprints are equal. Not for the alerts alone: a strip that is emptied, hidden, moved, muted or wrapped is a different fingerprint.
 */
export function stripFingerprint(el) {
  const root = el.shadowRoot;
  const strip = root ? root.querySelector('[data-ecco-alert-strip]') : null;
  if (!strip) return 'NO STRIP';
  const chain = [];
  for (let n = strip; n; n = n.parentNode || n.host || null) {
    if (n.nodeType === 1 && n.tagName !== '#shadow-root') chain.push(`${n.tagName} ${attrsOf(n, ['data-mode', 'data-theme'])}`);
  }
  const siblings = strip.parentNode ? strip.parentNode.childNodes : [];
  const before = siblings.slice(0, siblings.indexOf(strip)).map((c) => (c.nodeType === 1 ? `${c.tagName} ${attrsOf(c, ['data-mode', 'data-theme'])}` : '#text'));
  return JSON.stringify({ strip: serialise(strip), chain, before });
}

/**
 * The two ways the card reads a clock, as functions the tests call (a test body must not read a clock itself unless it is a [wall-clock] test: static.test.mjs). A call from a test file is moved by the scheduler only in the
 * scope 'tracked' (sched.withClockScope, sched.withBounds with clockScope): these are for the tests of the scheduler itself and of its synthetic cards.
 */
export const readPerformanceNow = () => performance.now();
export const readDateNow = () => Date.now();

export { tick, MEvent };
