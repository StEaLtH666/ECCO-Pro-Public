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

/** The occurrences of every token in the source: [{ token, line (1-based), key }]. */
export function asyncOccurrences(src) {
  const out = [];
  scanLines(src).forEach((l, idx) => {
    for (const [token, re] of Object.entries(ASYNC_TOKENS)) if (re.test(l.blank)) out.push({ token, line: idx + 1, key: siteKey(l.plain) });
  });
  return out;
}

/** The pin: { unlisted: occurrences that are not on the list (or are more than the list allows), missing: list entries that are not found as often as they say }. */
export function asyncSiteProblems(src, allowed = ALLOWED_ASYNC_SITES) {
  const found = new Map();
  for (const o of asyncOccurrences(src)) {
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
});

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
export function installScheduler({ resizeObservers = [], cardFile = CARD_PATH, bounds: boundsOverride = {} } = {}) {
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
  const peak = { work: 0, listeners: 0, alive: 0, records: 0, pending: 0, callbacksPerFlush: 0, eventsPerFlush: 0 }; // the largest each number has been in any test so far (a calibration, printed by the tests)
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
      return { work, records: records.length, listeners: pairs, pending: timers.size + frames.size + idles.size, bounds: { ...bounds } };
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
      sched.resetListeners();
      sched.clearAll();
    },
    /** Run `fn` (async) with other bounds, then put the old ones back: for the tests of the bounds themselves. The bounds that `fn` reached are forgotten afterwards, with everything it left waiting. */
    async withBounds(overrides, fn) {
      const old = bounds;
      bounds = { ...bounds, ...overrides };
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
    async flush({ rounds = bounds.maxRounds, events = false, after = null } = {}) {
      sched.check();
      charge(1);
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

export { tick, MEvent };
