// A strict reader for the shell stylesheet (not a test file: the test glob is test/*.test.mjs). Review round 3.
//
// Rounds 1 and 2 kept a list of ways to hide the alert strip and grew it each time a reviewer found a new one. This module does the opposite: it reads the
// stylesheet with a small tokenising parser that REFUSES what it cannot judge (a CSS escape, a comment, an @import, an at-rule or condition nobody pinned,
// a nested rule), and then offers two nets that never ask "is this a known way to hide the strip":
//
//   1. the PIN: canonicalSheet() turns the stylesheet into one canonical list of rules (at-rule context, selectors, declarations); the pin file holds the
//      list the owner's reviewers approved, and the test compares the two. Any new selector, any new declaration and any changed value, anywhere, fails
//      until a person edits the pin file in a reviewed diff.
//   2. the ALLOWLIST: stripProblems() decides which rules can reach the strip (it, what contains it, what it contains), and for those rules every
//      declaration must be on an allowlist of properties, each with a value check. A property that is not on the list is a violation however harmless it looks.
//
// The behavioural net (preview/check-strip.mjs, headless Chrome) is the third and does not read the stylesheet at all.

const WS = /\s+/g;
const collapse = (s) => s.replace(WS, ' ').trim();

// ---------------------------------------------------------------------------------------------------------------------------
// the parser
// ---------------------------------------------------------------------------------------------------------------------------
/** The at-rules (with their conditions) the stylesheet may contain. Anything else is a problem, however harmless. */
export const PINNED_AT_RULES = Object.freeze([
  '@media (prefers-color-scheme: dark)',
  '@media (prefers-reduced-motion: no-preference)',
  '@media (prefers-reduced-motion: reduce)',
  '@container (min-width:561px)',
  '@container (max-width:560px)',
  '@keyframes ecco-pulse',
]);

/** Index of the character that ends the text at depth 0 for one of `stops`, skipping quotes, (), [] and {} . -1 when there is none. */
function scanTop(text, from, stops) {
  let quote = null;
  let paren = 0;
  let bracket = 0;
  for (let i = from; i < text.length; i += 1) {
    const c = text[i];
    if (quote) {
      if (c === quote) quote = null;
    } else if (c === '"' || c === "'") quote = c;
    else if (c === '(') paren += 1;
    else if (c === ')') paren = Math.max(0, paren - 1);
    else if (c === '[') bracket += 1;
    else if (c === ']') bracket = Math.max(0, bracket - 1);
    else if (paren === 0 && bracket === 0 && stops.includes(c)) return i;
  }
  return -1;
}

/** Index of the } that matches the { at `open` (quote aware), or -1. */
function matchBrace(text, open) {
  let depth = 0;
  let quote = null;
  for (let i = open; i < text.length; i += 1) {
    const c = text[i];
    if (quote) {
      if (c === quote) quote = null;
    } else if (c === '"' || c === "'") quote = c;
    else if (c === '{') depth += 1;
    else if (c === '}') {
      depth -= 1;
      if (depth === 0) return i;
    }
  }
  return -1;
}

/** Split at top-level occurrences of `sep` (a single character). */
export function splitTop(text, sep) {
  const out = [];
  let from = 0;
  for (let i = scanTop(text, 0, sep); i !== -1; i = scanTop(text, from, sep)) {
    out.push(text.slice(from, i));
    from = i + 1;
  }
  out.push(text.slice(from));
  return out;
}

/** Split a value at top-level white space. */
export function splitSpaces(text) {
  const out = [];
  let from = 0;
  let quote = null;
  let paren = 0;
  for (let i = 0; i <= text.length; i += 1) {
    const c = text[i];
    if (i < text.length && quote) {
      if (c === quote) quote = null;
      continue;
    }
    if (c === '"' || c === "'") quote = c;
    else if (c === '(') paren += 1;
    else if (c === ')') paren = Math.max(0, paren - 1);
    else if ((i === text.length || /\s/.test(c)) && paren === 0) {
      if (i > from) out.push(text.slice(from, i));
      from = i + 1;
    }
  }
  return out;
}

/** One selector in its canonical spelling: white space collapsed, none around a combinator (outside quotes, brackets and parentheses). */
export function normaliseSelector(sel) {
  let out = '';
  let quote = null;
  let paren = 0;
  let bracket = 0;
  const text = collapse(sel);
  for (let i = 0; i < text.length; i += 1) {
    const c = text[i];
    if (quote) {
      out += c;
      if (c === quote) quote = null;
    } else if (c === '"' || c === "'") {
      quote = c;
      out += c;
    } else if (c === '(') {
      paren += 1;
      out += c;
    } else if (c === ')') {
      paren = Math.max(0, paren - 1);
      out += c;
    } else if (c === '[') {
      bracket += 1;
      out += c;
    } else if (c === ']') {
      bracket = Math.max(0, bracket - 1);
      out += c;
    } else if (paren === 0 && bracket === 0 && (c === '>' || c === '+' || c === '~')) {
      out = out.replace(/ $/, '') + c;
      while (text[i + 1] === ' ') i += 1;
    } else out += c;
  }
  return out;
}

function parseDecls(body, problems, where) {
  const decls = [];
  for (const raw of splitTop(body, ';')) {
    const d = raw.trim();
    if (d === '') continue;
    const k = scanTop(d, 0, ':');
    if (k === -1) {
      problems.push(`a declaration without a colon in ${where}: ${d.slice(0, 40)}`);
      continue;
    }
    const name = d.slice(0, k).trim();
    if (!/^(?:--[A-Za-z0-9_-]+|-?[A-Za-z][A-Za-z0-9-]*)$/.test(name)) {
      problems.push(`a property name that is not a plain identifier in ${where}: ${name.slice(0, 40)}`);
      continue;
    }
    let value = d.slice(k + 1).trim();
    const important = /!\s*important\s*$/i.test(value);
    if (important) value = value.replace(/!\s*important\s*$/i, '').trim();
    if (value === '') {
      problems.push(`an empty value in ${where}: ${name}`);
      continue;
    }
    decls.push({ prop: name.startsWith('--') ? name : name.toLowerCase(), value: collapse(value), important });
  }
  return decls;
}

function parseList(text, at, out, problems, keyframes) {
  let pos = 0;
  while (pos < text.length) {
    while (pos < text.length && /\s/.test(text[pos])) pos += 1;
    if (pos >= text.length) break;
    const stop = scanTop(text, pos, '{;}');
    if (stop === -1) {
      problems.push(`text that ends without a block: ${text.slice(pos, pos + 40)}`);
      return;
    }
    const prelude = collapse(text.slice(pos, stop));
    if (text[stop] === '}') {
      problems.push('an unmatched closing brace');
      pos = stop + 1;
      continue;
    }
    if (text[stop] === ';') {
      problems.push(`a statement at-rule or stray text (an @import, @charset or @namespace is not allowed): ${prelude.slice(0, 50)}`);
      pos = stop + 1;
      continue;
    }
    const close = matchBrace(text, stop);
    if (close === -1) {
      problems.push(`unbalanced braces after: ${prelude.slice(0, 50)}`);
      return;
    }
    const body = text.slice(stop + 1, close);
    if (prelude.startsWith('@')) {
      if (at.length > 0) problems.push(`an at-rule inside an at-rule: ${prelude.slice(0, 50)}`);
      else if (!PINNED_AT_RULES.includes(prelude)) problems.push(`an at-rule or condition that is not on the pinned list: ${prelude.slice(0, 70)}`);
      parseList(body, [...at, prelude], out, problems, /^@(?:-[a-z]+-)?keyframes\b/i.test(prelude));
    } else {
      if (scanTop(body, 0, '{') !== -1) problems.push(`a rule nested inside a rule (CSS nesting): ${prelude.slice(0, 50)}`);
      if (/&/.test(prelude)) problems.push(`a nesting selector (&): ${prelude.slice(0, 50)}`);
      const selectors = splitTop(prelude, ',').map(normaliseSelector).filter(Boolean);
      if (selectors.length === 0) problems.push('a rule without a selector');
      out.push({ at, selectors, decls: parseDecls(body, problems, prelude.slice(0, 40)), keyframes });
    }
    pos = close + 1;
  }
}

/** Every rule of a stylesheet and every reason the parser refused to judge some of it. */
export function parseSheet(css) {
  const problems = [];
  const text = String(css);
  if (text.includes('\\')) problems.push('a backslash: CSS escapes are not read, so a selector or property could be spelled in a way this reader does not see');
  if (text.includes('/*')) problems.push('a CSS comment: a comment inside a selector or between a property and its colon changes what a rule means');
  if (/<|-->/.test(text)) problems.push('an HTML comment token (<!-- or -->)');
  // eslint-disable-next-line no-control-regex
  if (/[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]/.test(text)) problems.push('a control character');
  const rules = [];
  parseList(text, [], rules, problems, false);
  return { rules, problems: [...new Set(problems)] };
}

/** The canonical form the pin file holds: rules in source order, each { at, selectors, decls: [[property, value, '!important' or '']] }. */
export function canonicalSheet(css) {
  const { rules, problems } = parseSheet(css);
  return {
    problems,
    rules: rules.map((r) => ({ at: r.at, selectors: r.selectors, decls: r.decls.map((d) => [d.prop, d.value, d.important ? '!important' : '']) })),
  };
}

// ---------------------------------------------------------------------------------------------------------------------------
// the pin
// ---------------------------------------------------------------------------------------------------------------------------
const ruleLabel = (r) => `${r.at.length ? `${r.at.join(' ')} { ` : ''}${r.selectors.join(', ')}`;

/** What differs between the pin and the stylesheet, in words a reviewer can act on ([] when they are identical, rule for rule and in the same order). */
export function pinProblems(css, pin) {
  const got = canonicalSheet(css);
  const out = got.problems.map((p) => `the stylesheet cannot be read: ${p}`);
  const gotJson = got.rules.map((r) => JSON.stringify(r));
  const wantJson = pin.rules.map((r) => JSON.stringify(r));
  const count = (arr) => arr.reduce((m, x) => m.set(x, (m.get(x) || 0) + 1), new Map());
  const gc = count(gotJson);
  const wc = count(wantJson);
  for (const [j, n] of gc) if ((wc.get(j) || 0) < n) out.push(`a rule, selector or declaration that is not in the pin: ${ruleLabel(JSON.parse(j))} ${JSON.stringify(JSON.parse(j).decls)}`);
  for (const [j, n] of wc) if ((gc.get(j) || 0) < n) out.push(`a pinned rule that is missing or changed: ${ruleLabel(JSON.parse(j))}`);
  if (out.length === 0 && gotJson.join('\n') !== wantJson.join('\n')) out.push('the rules are the pinned ones but in another order (the cascade would change)');
  return [...new Set(out)];
}

// ---------------------------------------------------------------------------------------------------------------------------
// which rules can reach the strip
// ---------------------------------------------------------------------------------------------------------------------------
/** Case-insensitive: attribute names and values in a selector are matched without regard to case by the browser (for HTML attributes). */
export const ALERT_TOKEN = /\.alerts?\b|data-ecco-alert-strip|data-alert|data-severity|\[\s*(?:[a-z*]*\|)?(?:role|aria-live|aria-label|aria-atomic|aria-relevant)\b|\brole\s*=/i;
export const MODE_TOKEN = /data-mode|data-ecco-body|data-ecco-mode|data-geek|data-production|(?<![a-z0-9_-])(?:geek|production)(?![a-z0-9_-])/i;

/** The classes the strip, the elements that contain it and the elements it contains can carry (the shell is its parent; the quiet line is an .alert.quiet). */
export const STRIP_FAMILY = Object.freeze(new Set(['shell', 'alerts', 'alert', 'alert-head', 'alert-action', 'ico', 'quiet']));

/** The compound selectors of one complex selector (split at descendant, child and sibling combinators outside brackets, parentheses and quotes). */
export function compounds(sel) {
  const out = [];
  let from = 0;
  let quote = null;
  let paren = 0;
  let bracket = 0;
  for (let i = 0; i <= sel.length; i += 1) {
    const c = sel[i];
    if (i < sel.length && quote) {
      if (c === quote) quote = null;
      continue;
    }
    if (c === '"' || c === "'") quote = c;
    else if (c === '(') paren += 1;
    else if (c === ')') paren = Math.max(0, paren - 1);
    else if (c === '[') bracket += 1;
    else if (c === ']') bracket = Math.max(0, bracket - 1);
    else if ((i === sel.length || (paren === 0 && bracket === 0 && (c === ' ' || c === '>' || c === '+' || c === '~')))) {
      if (i > from) out.push(sel.slice(from, i));
      from = i + 1;
    }
  }
  return out;
}

/**
 * True when a rule with this selector can style the alert strip, something that contains it, or something it contains. It cannot when a compound of the
 * selector asks for a class that none of those elements carries (a rule on `.row` or on `.healthbar>span` can never apply to the strip), or for an id
 * (nothing there has one). Everything else can: a tag, `*`, an attribute, a pseudo-class, :host, and anything that names the strip.
 */
export function reachesStripStrict(sel) {
  if (ALERT_TOKEN.test(sel)) return true;
  for (const c of compounds(sel)) {
    const bare = c.replace(/\[[^\]]*\]/g, '').replace(/:{1,2}[a-z-]+(?:\([^)]*\))?/gi, '');
    if (/#[A-Za-z0-9_-]/.test(bare)) return false;
    for (const m of bare.matchAll(/\.([A-Za-z0-9_-]+)/g)) if (!STRIP_FAMILY.has(m[1])) return false;
  }
  return true;
}

// ---------------------------------------------------------------------------------------------------------------------------
// the allowlist for rules that reach the strip
// ---------------------------------------------------------------------------------------------------------------------------
/** The only custom properties and var() names a rule that reaches the strip may define or read. */
export const THEME_VARS = Object.freeze(new Set(['--ecco-live', '--ecco-stale', '--ecco-unavailable', '--ecco-unknown', '--ecco-simulated', '--ecco-unverified', '--ecco-accent',
  '--ecco-surface', '--ecco-fg', '--ecco-fg2', '--ecco-line', '--ecco-chip', '--ecco-track', '--ecco-focus', '--ecco-st']));
/** Home Assistant's own theme variables, which the shell reads (never defines) with a fallback. */
export const HA_VARS = Object.freeze(new Set(['--card-background-color', '--primary-text-color', '--secondary-text-color', '--divider-color']));
const FONT_VAR = '--paper-font-body1_-_font-family';

const NAMED_COLOURS = new Set(['white', 'black', 'red', 'green', 'blue', 'yellow', 'orange', 'purple', 'gray', 'grey', 'silver', 'navy', 'teal', 'currentcolor', 'inherit']);

/** The alpha of a colour token, or null when the token is not a colour this reader understands (a gradient, hsl(), a keyword such as transparent, ...). */
export function colourAlpha(token, depth = 0) {
  const t = String(token).trim().toLowerCase();
  if (depth > 3) return null;
  let m = /^#([0-9a-f]+)$/.exec(t);
  if (m) {
    const h = m[1];
    if (h.length === 3 || h.length === 6) return 1;
    if (h.length === 4) return Number.parseInt(h[3], 16) / 15;
    if (h.length === 8) return Number.parseInt(h.slice(6), 16) / 255;
    return null;
  }
  if (NAMED_COLOURS.has(t)) return 1;
  m = /^rgba?\(([^()]*)\)$/.exec(t);
  if (m) {
    const parts = m[1].split(/[\s,/]+/).filter(Boolean);
    if (parts.length < 3 || parts.length > 4) return null;
    if (!parts.slice(0, 3).every((p) => /^\d+(?:\.\d+)?%?$/.test(p))) return null;
    if (parts.length === 3) return 1;
    const a = /^(\d*\.?\d+)(%?)$/.exec(parts[3]);
    if (!a) return null;
    return a[2] ? Number(a[1]) / 100 : Number(a[1]);
  }
  m = /^var\(\s*(--[a-z0-9_-]+)\s*(?:,(.*))?\)$/.exec(t);
  if (m) {
    if (!THEME_VARS.has(m[1]) && !HA_VARS.has(m[1])) return null;
    if (m[2] === undefined) return 1;
    return colourAlpha(m[2], depth + 1);
  }
  return null;
}
const colour = (minAlpha) => (v) => {
  const a = colourAlpha(v);
  return a !== null && a >= minAlpha;
};

const LENGTH = /^(\d*\.?\d+)(px|rem|em|%)?$/;
/** A list of non-negative lengths (zero needs no unit), each at most `max` px (1 rem = 1 em = 16 px; a percentage counts as itself). */
function lengths(v, max, count = 4) {
  const parts = splitSpaces(v);
  if (parts.length < 1 || parts.length > count) return false;
  return parts.every((p) => {
    const m = LENGTH.exec(p);
    if (!m) return false;
    const n = Number(m[1]);
    if (n === 0) return true;
    if (!m[2]) return false;
    return (m[2] === 'rem' || m[2] === 'em' ? n * 16 : n) <= max;
  });
}
const px = (v) => {
  const m = /^(\d*\.?\d+)(px|rem|em)$/.exec(v);
  return m ? (m[2] === 'px' ? Number(m[1]) : Number(m[1]) * 16) : null;
};
const oneOf = (...words) => (v) => words.includes(v);

const TRACK = /^(?:auto|1fr|minmax\(\s*(?:0|\d+px)\s*,\s*1fr\s*\))$/;
function borderValue(v) {
  const parts = splitSpaces(v);
  if (parts.length < 1 || parts.length > 3) return false;
  return parts.every((p) => {
    if (/^(?:solid|dashed|dotted|double)$/.test(p)) return true;
    const w = px(p);
    if (w !== null) return w <= 8;
    if (p === '0') return true;
    return colour(0.15)(p);
  });
}
function fontShorthand(v) {
  const m = /^(\d*\.?\d+)(px|rem|em)\/(\d*\.?\d+) (.+)$/.exec(v);
  if (!m) return false;
  const size = m[2] === 'px' ? Number(m[1]) : Number(m[1]) * 16;
  if (size < 12 || Number(m[3]) < 1) return false;
  const fam = m[4];
  const inVar = /^var\(\s*--paper-font-body1_-_font-family\s*,[^()]*\)$/.test(fam);
  return inVar || /^[A-Za-z0-9 ,"'-]+$/.test(fam);
}

/**
 * Property -> value check for a declaration in a rule that can reach the strip. A property that is not here is a violation, so there is no list of
 * "known ways to hide": transform, rotate, scale, translate, filter, opacity, clip-path, mask, line-height, max-height, overflow, visibility, position,
 * order, z-index, contain, text-indent, pointer-events, inset and the rest are refused because nobody listed them. Each value is bounded too.
 */
export const STRIP_ALLOWLIST = Object.freeze({
  display: oneOf('grid', 'flex', 'block', 'inline-grid', 'inline-flex'),
  'container-type': oneOf('inline-size'),
  'box-sizing': oneOf('border-box'),
  'min-width': oneOf('0'),
  'max-width': oneOf('100%'),
  gap: (v) => lengths(v, 32, 2),
  padding: (v) => lengths(v, 48),
  margin: (v) => lengths(v, 24) || v === '0 auto',
  'overflow-wrap': oneOf('anywhere', 'break-word', 'normal'),
  'grid-template-columns': (v) => { const t = splitSpaces(v); return t.length >= 1 && t.length <= 4 && t.every((x) => TRACK.test(x)); },
  'grid-row': (v) => /^(?:auto|\d(?:\/\d)?)$/.test(v),
  'grid-column': (v) => /^(?:auto|\d(?:\/\d)?)$/.test(v),
  'align-items': oneOf('start', 'center', 'stretch', 'baseline'),
  color: colour(0.6),
  background: colour(0.9),
  'background-color': colour(0.9),
  'border-color': colour(0.15),
  'border-left-color': colour(0.15),
  border: borderValue,
  'border-left': borderValue,
  'border-style': oneOf('solid', 'dashed', 'dotted', 'double'),
  'border-width': (v) => lengths(v, 6),
  'border-radius': (v) => lengths(v, 999),
  outline: borderValue,
  'outline-offset': (v) => lengths(v, 8, 1),
  font: fontShorthand,
  'font-size': (v) => { const n = px(v); return n !== null && n >= 12; },
  'font-weight': (v) => /^(?:normal|bold|[1-9]00)$/.test(v),
  fill: oneOf('none'),
  stroke: oneOf('currentcolor'),
  'stroke-width': (v) => /^[123]$/.test(v),
  'stroke-linecap': oneOf('round'),
  'stroke-linejoin': oneOf('round'),
  flex: oneOf('none'),
  animation: oneOf('none'),
  transition: oneOf('none'),
  'scroll-behavior': oneOf('auto'),
});
/** width and height only on the small icon (16 to 48 px): on anything else they could collapse or stretch the strip. */
const ICON_SIZE = (v) => { const n = px(v); return n !== null && n >= 16 && n <= 48; };

/** Where an !important is allowed in a rule that reaches the strip: the one reduced-motion rule. */
const IMPORTANT_OK = (r) => r.at.length === 1 && r.at[0] === '@media (prefers-reduced-motion: reduce)';

/** The one rule that may hide anything: the standard [hidden] attribute rule. */
const isHiddenRule = (r) => r.selectors.length === 1 && r.selectors[0] === '[hidden]' && r.at.length === 0;
const hiddenRuleOk = (r) => r.decls.length === 1 && r.decls[0].prop === 'display' && r.decls[0].value.toLowerCase() === 'none' && r.decls[0].important;

/** Selectors that use a pseudo-class the strict reader otherwise refuses (:not, :has, :is, :where, a positional one): pinned by full text. */
export const PINNED_PSEUDO_SELECTORS = Object.freeze(new Set(['.shell:not([data-theme="light"])']));
const PSEUDO = /:(?:not|has|is|where|matches|host-context|-webkit-any|-moz-any|first-child|last-child|only-child|nth-child|nth-last-child|first-of-type|last-of-type|only-of-type|nth-of-type|nth-last-of-type|empty|scope|root)\b|::slotted|::part|&/i;

/**
 * Every reason a rule that can reach the alert strip is not acceptable, plus the refusals that apply to every rule (nesting, escapes and the like come from
 * parseSheet). [] when the stylesheet is acceptable. `modeSelectors` and `stripSelectors` are the pinned lists of the selectors that may name a mode or the
 * strip (see the static test).
 */
export function stripProblems(css, { modeSelectors, stripSelectors }) {
  const { rules, problems } = parseSheet(css);
  const bad = problems.map((p) => `unreadable: ${p}`);
  for (const r of rules) {
    if (r.keyframes) {
      for (const d of r.decls) if (d.prop !== 'box-shadow') bad.push(`a keyframe sets ${d.prop}: only box-shadow may be animated`);
      continue;
    }
    if (isHiddenRule(r)) {
      if (!hiddenRuleOk(r)) bad.push('the [hidden] rule is anything but display:none!important');
      continue;
    }
    for (const s of r.selectors) {
      if (MODE_TOKEN.test(s) && !modeSelectors.has(s)) bad.push(`mode-dependent selector: ${s}`);
      if (ALERT_TOKEN.test(s) && !stripSelectors.has(s)) bad.push(`a selector names the alert strip and is not on the pinned list: ${s}`);
      if (PSEUDO.test(s.replace(/"[^"]*"|'[^']*'/g, '""')) && !PINNED_PSEUDO_SELECTORS.has(s)) bad.push(`a selector with :not, :has, :is, :where, a positional pseudo-class or & outside the pinned list: ${s}`);
      if (/\[\s*hidden\b/i.test(s)) bad.push(`a selector that depends on the hidden attribute: ${s}`);
      if (/[+~]/.test(s.replace(/\[[^\]]*\]/g, '').replace(/\([^)]*\)/g, ''))) bad.push(`a selector with a sibling combinator: ${s}`);
    }
    const reaching = r.selectors.filter(reachesStripStrict);
    if (reaching.length === 0) continue;
    const label = reaching[0];
    const lastIsIcon = reaching.every((s) => /\.ico\b/.test(compounds(s).slice(-1)[0] || ''));
    for (const d of r.decls) {
      const v = d.value.toLowerCase();
      const at = `${label} { ${d.prop}: ${d.value} }`;
      if (d.important && !IMPORTANT_OK(r)) bad.push(`!important in a rule that reaches the strip: ${at}`);
      if (d.prop.startsWith('--')) {
        if (!THEME_VARS.has(d.prop)) bad.push(`a custom property that is not on the pinned theme list, in a rule that reaches the strip: ${at}`);
        else if (!colour(0.1)(v)) bad.push(`a theme property whose value is not a visible colour: ${at}`);
        continue;
      }
      if ((d.prop === 'width' || d.prop === 'height') && lastIsIcon) {
        if (!ICON_SIZE(v)) bad.push(`an icon size outside 16 to 48 px: ${at}`);
        continue;
      }
      const ok = Object.prototype.hasOwnProperty.call(STRIP_ALLOWLIST, d.prop) ? STRIP_ALLOWLIST[d.prop] : null;
      if (ok === null) bad.push(`a property that is not on the allowlist for rules that reach the strip: ${at}`);
      else if (!ok(v)) bad.push(`a value outside what the allowlist accepts for ${d.prop}: ${at}`);
      for (const m of v.matchAll(/var\(\s*(--[a-z0-9_-]+)/g)) {
        const colourProp = /^(?:color|background(?:-color)?|border(?:-[a-z]+)*|outline(?:-color)?)$/.test(d.prop);
        const fine = (colourProp && (THEME_VARS.has(m[1]) || HA_VARS.has(m[1]))) || (d.prop === 'font' && m[1] === FONT_VAR);
        if (!fine) bad.push(`var(${m[1]}) outside a colour or the font family, or not a pinned theme name, in a rule that reaches the strip: ${at}`);
      }
    }
  }
  return [...new Set(bad)];
}
