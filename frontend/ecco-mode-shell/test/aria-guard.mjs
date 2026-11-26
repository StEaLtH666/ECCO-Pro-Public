// The accessibility-state guard (review round 4). Test-side only; the card is read, never changed.
//
// What it protects: what a screen-reader user gets from the alert strip must be the same in Production and Geek Mode. The strip is a labelled region that is
// announced politely, its alerts carry the roles alert / status, and nothing in the shell may hide it from assistive technology (aria-hidden, inert, hidden,
// role=presentation / none, an aria-live that is not polite, an empty label). The CSS nets (css-guard.mjs, the pin) cannot see those: they are ATTRIBUTES, and an
// attribute can be written by one line of code. A reviewer's mutants did exactly that and survived every suite:
//   J2  ui.strip.setAttribute('aria-hidden', mode === 'geek' ? 'true' : 'false')
//   J5  ui.strip.setAttribute('aria-live', mode === 'geek' ? 'off' : 'polite')
//
// The rule is structural, as the stylesheet's was in round 3: the card may write an attribute at the SITES listed in ARIA_PIN and nowhere else. A new site, a
// changed receiver or attribute, a name that is not a plain literal, or any other way of reaching an accessibility property is refused until a person has decided it
// (and edited the pin in the same commit). Three nets stand behind this one: test/element.test.mjs compares the strip's attributes in both modes in the DOM stand-in,
// test/mutations.test.mjs proves the mutants above (and the variants listed there) are killed, and preview/check-strip.mjs compares the attributes in a real browser.
//
// Limit (documented in the design document): a static read of source cannot exclude every dynamic way to write an attribute (a method name built at run time, say).
// The card already forbids eval, Function, Reflect, Proxy, globalThis and the other doors, this guard refuses the aliasing and bracket forms of the three attribute
// methods, and the two behavioural nets look at the result, not at the source.

/** The card's source without its stylesheet (the CSS has selectors such as [aria-checked="true"], which are not writes). Comments must already be stripped. */
export function withoutStyle(code) {
  return code.replace(/export const STYLE = `[\s\S]*?\n`;/, '');
}

const METHODS = ['setAttribute', 'toggleAttribute', 'removeAttribute'];
const IDENT = /[A-Za-z0-9_$.[\]]/;

/** Index of the bracket that closes the one opened at `open` (a quote- and bracket-aware scan); -1 when unbalanced. */
function closeOf(text, open) {
  const pairs = { '(': ')', '[': ']', '{': '}' };
  const stack = [pairs[text[open]]];
  for (let i = open + 1; i < text.length; i += 1) {
    const c = text[i];
    if (c === "'" || c === '"' || c === '`') {
      for (i += 1; i < text.length && text[i] !== c; i += 1) if (text[i] === '\\') i += 1;
    } else if (pairs[c]) stack.push(pairs[c]);
    else if (c === stack[stack.length - 1]) {
      stack.pop();
      if (stack.length === 0) return i;
    }
  }
  return -1;
}

/** The first top-level argument of a call's argument text. */
function firstArg(args) {
  let depth = 0;
  for (let i = 0; i < args.length; i += 1) {
    const c = args[i];
    if (c === "'" || c === '"' || c === '`') {
      for (i += 1; i < args.length && args[i] !== c; i += 1) if (args[i] === '\\') i += 1;
    } else if (c === '(' || c === '[' || c === '{') depth += 1;
    else if (c === ')' || c === ']' || c === '}') depth -= 1;
    else if (c === ',' && depth === 0) return args.slice(0, i).trim();
  }
  return args.trim();
}

/** The text just before the dot of a method call: `ui.opts[m]`, `svg`, `this._root.querySelector('x')`. */
function receiverOf(text, dot) {
  let i = dot;
  while (i > 0 && /\s/.test(text[i - 1])) i -= 1; // a method chain may be broken over lines: `ui.x\n  .setAttribute(`
  const end = i;
  while (i > 0) {
    const c = text[i - 1];
    if (IDENT.test(c)) i -= 1;
    else if (c === ')') {
      let depth = 0;
      let j = i - 1;
      for (; j >= 0; j -= 1) {
        if (text[j] === ')') depth += 1;
        else if (text[j] === '(') {
          depth -= 1;
          if (depth === 0) break;
        }
      }
      i = j;
    } else break;
  }
  return text.slice(i, end).replace(/\s+/g, ' ').trim();
}

/** Every call of setAttribute, toggleAttribute and removeAttribute: [{ method, receiver, first }] in source order. */
export function attributeCalls(code) {
  const out = [];
  const re = new RegExp(`\\.\\s*(${METHODS.join('|')})\\s*\\(`, 'g');
  for (let m = re.exec(code); m; m = re.exec(code)) {
    const open = m.index + m[0].length - 1;
    const close = closeOf(code, open);
    out.push({ method: m[1], receiver: receiverOf(code, m.index), first: close === -1 ? '(unbalanced)' : firstArg(code.slice(open + 1, close)) });
  }
  return out;
}

/** The keys of object literals that name an accessibility, visibility or focus state: { key (lower case): how many times it is written }. */
export function stateKeys(code) {
  const re = /(?<=[{,]\s*)(?:'((?:aria-[A-Za-z-]+|role|hidden|inert|style|tabindex|slot|part|popover|contenteditable))'|\b(role|hidden|inert|style|tabindex|slot|part|popover|contenteditable))\s*:(?!:)/g;
  const out = {};
  for (let m = re.exec(code); m; m = re.exec(code)) {
    const k = (m[1] || m[2]).toLowerCase();
    out[k] = (out[k] || 0) + 1;
  }
  return Object.fromEntries(Object.entries(out).sort(([a], [b]) => (a < b ? -1 : 1)));
}

/** Other doors to an attribute or to an accessibility property: refused wherever they appear (none is used by the card today). */
export const FORBIDDEN = Object.freeze([
  [/\b(?:setAttributeNode|removeAttributeNode|setAttributeNodeNS|removeAttributeNodeNS|setAttributeNS|removeAttributeNS|toggleAttributeNS|setNamedItem|removeNamedItem|setNamedItemNS|removeNamedItemNS|attachInternals|createAttribute|createAttributeNS)\b/,
    'an attribute written by a node or a named-item API'],
  [/\.\s*(?:role|aria[A-Z][A-Za-z]*)\b/, 'an ARIA reflection property (el.role, el.ariaHidden, el.ariaLive ...)'],
  [/\[\s*(['"`])\s*(?:role|aria[A-Za-z]*)\s*\1\s*\]/i, 'an ARIA reflection property by bracket'],
  [/\.\s*(?:classList|className|inert|slot|tabIndex|contentEditable|popover)\b/, 'a class, inert, slot, tabindex, contenteditable or popover property'],
  [/\bObject\s*\.\s*(?:assign|defineProperty|defineProperties|setPrototypeOf)\b/, 'Object.assign / defineProperty onto an object that may be an element'],
  [new RegExp(`\\.\\s*(?:${METHODS.join('|')})\\b(?!\\s*\\()`), 'an attribute method used without being called at once (an alias, call, apply or bind)'],
  [new RegExp(`\\[\\s*['"\`](?:${METHODS.join('|')})['"\`]\\s*\\]`), 'an attribute method reached by bracket'],
]);

/** What a person has approved. Change it only in the commit that adds the write, with a reason. */
export const ARIA_PIN = Object.freeze({
  // [method, first argument as written, receiver as written]: every place the card writes, toggles or removes an attribute by method call
  sites: Object.freeze([
    ['removeAttribute', "'data-theme'", 'ui.shell'],
    ['setAttribute', "'aria-checked'", 'ui.opts[m]'],
    ['setAttribute', "'aria-hidden'", 'svg'],
    ['setAttribute', "'aria-pressed'", 'ui.problems'],
    ['setAttribute', "'class'", 'svg'],
    ['setAttribute', "'data-alert-count'", 'strip'],
    ['setAttribute', "'data-level'", 'ui.summary'],
    ['setAttribute', "'data-mode'", 'ui.shell'],
    ['setAttribute', "'data-mode'", 'ui.sw'],
    ['setAttribute', "'data-theme'", 'ui.shell'],
    ['setAttribute', "'download'", 'a'],
    ['setAttribute', "'href'", 'a'],
    ['setAttribute', "'tabindex'", 'ui.opts[m]'],
    ['setAttribute', "'viewBox'", 'svg'],
    ['setAttribute', 'k', 'el'],
    ['setAttribute', 'k', 'n'],
    ['toggleAttribute', "'disabled'", 'ui.next'],
    ['toggleAttribute', "'disabled'", 'ui.prev'],
  ]),
  // the accessibility, visibility and focus keys of every object literal (the literals that build elements), counted
  // (no hidden, inert, style, slot, part, popover or contenteditable key anywhere: a count of zero is the pin, and the keys that are absent here are zero)
  keys: Object.freeze({ 'aria-checked': 1, 'aria-expanded': 2, 'aria-hidden': 2, 'aria-label': 16, 'aria-live': 2, 'aria-pressed': 2, role: 10, tabindex: 2 }),
});

const showSite = (s) => `${s[0]}(${s[1]}) on ${s[2]}`;

/** Problems with the card's attribute writes (comment-stripped source). [] means every write is at a pinned site and no other door is used. */
export function ariaProblems(codeWithStyle, pin = ARIA_PIN) {
  const code = withoutStyle(codeWithStyle);
  const problems = [];
  const calls = attributeCalls(code);
  for (const c of calls) {
    if (!(/^'[^'\\]*'$/.test(c.first) || c.first === 'k')) problems.push(`the attribute name of ${c.method} on ${c.receiver} is not a plain single-quoted literal (or k in the two builders): ${c.first}`);
  }
  const have = new Map();
  for (const c of calls) {
    const k = showSite([c.method, c.first, c.receiver]);
    have.set(k, (have.get(k) || 0) + 1);
  }
  const want = new Map();
  for (const s of pin.sites) want.set(showSite(s), (want.get(showSite(s)) || 0) + 1);
  for (const [k, n] of have) if ((want.get(k) || 0) !== n) problems.push(`attribute write not pinned (or pinned a different number of times): ${k} x${n}, pinned x${want.get(k) || 0}`);
  for (const [k, n] of want) if (!have.has(k)) problems.push(`pinned attribute write is gone: ${k} x${n}`);
  const keys = stateKeys(code);
  for (const k of new Set([...Object.keys(keys), ...Object.keys(pin.keys)])) {
    if ((keys[k] || 0) !== (pin.keys[k] || 0)) problems.push(`the key '${k}' is written ${keys[k] || 0} time(s) in object literals, pinned ${pin.keys[k] || 0}`);
  }
  for (const [re, what] of FORBIDDEN) {
    const m = re.exec(code);
    if (m) problems.push(`${what}: ${m[0].replace(/\s+/g, ' ')}`);
  }
  return problems;
}
