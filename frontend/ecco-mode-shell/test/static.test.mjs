// Source-level pins (node side). The card must have no write, network, storage, history or dynamic-code API; read hass.states,
// hass.locale and hass.themes only; build every node with node APIs (never markup); keep the mode in one controller and nowhere
// else; use ONE snapshot adapter and ONE alert-strip renderer; carry no URL or external resource; and ship only text, as LF.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';
import { cardDir, CARD_PATH, cardUrl } from './helpers.mjs';
import { ALERT_TOKEN, MODE_TOKEN, parseSheet, pinProblems, stripProblems, reachesStripStrict, compounds, STRIP_ALLOWLIST, THEME_VARS } from './css-guard.mjs';
import { ariaProblems, attributeCalls, stateKeys, withoutStyle, ARIA_PIN, FORBIDDEN } from './aria-guard.mjs';
import { expressionAccesses, doorsIn, skeleton } from './member-guard.mjs';
import { TRIPWIRE_NAMES } from './minidom.mjs';

const src = readFileSync(CARD_PATH, 'utf8');
const code = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:'"`\\])\/\/.*$/gm, '$1');
const names = (re, text = code) => [...text.matchAll(re)].map((m) => m[1]);
const uniq = (a) => [...new Set(a)].sort();

test('no write, network, storage, history or dynamic-code API anywhere in the module (comments stripped)', () => {
  for (const re of [
    /\bcallService\b/, /\bcallWS\b/, /\bcallApi\b/, /\bsendMessage\b/, /\bsendWS\b/, /\bfetchWithAuth\b/, /\bsubscribeEvents\b/, /\bsubscribeMessage\b/,
    /\bXMLHttpRequest\b/, /\bWebSocket\b/, /\bEventSource\b/, /\bsendBeacon\b/, /\bBroadcastChannel\b/, /\bSharedWorker\b/, /\bServiceWorker\b/, /\bpostMessage\b/,
    /\blocalStorage\b/, /\bsessionStorage\b/, /\bindexedDB\b/i, /\bcookieStore\b/, /\bdocument\s*\.\s*cookie\b/, /\bcaches\b/,
    /\bpushState\b/, /\breplaceState\b/, /\bhistory\b/, /\bwindow\s*\.\s*open\b/, /\bfetch\s*\(/, /\beval\s*\(/, /\bnew\s+Function\b/, /\bimport\s*\(/,
    /^\s*import\s/m, /\brequire\s*\(/, /\.connection\b/, /\bhass-action\b/, /\bperform_action\s*\(/, /\bsetTimeout\s*\(/, /\brequestAnimationFrame\s*\(/,
    /\bglobalThis\b/, /\bdocument\b/, /\bReflect\b/, /\bProxy\b/, /\bFunction\s*\(/,
  ]) assert.doesNotMatch(code, re, String(re));
});

test('no markup is ever built from strings: no innerHTML, outerHTML, insertAdjacentHTML, document.write or innerText', () => {
  for (const re of [/\binnerHTML\b/, /\bouterHTML\b/, /\binsertAdjacentHTML\b/, /\bdocument\.write\b/, /\binnerText\b/, /\bsrcdoc\b/, /\.cssText\b/, /\bsetAttributeNS\b/, /\bsetHTML\b/, /\bDOMParser\b/, /\bcreateContextualFragment\b/]) {
    assert.doesNotMatch(code, re, String(re));
  }
});

test('element and attribute NAMES are never computed from data: every tag and attribute name is a literal or a fixed internal variable', () => {
  assert.deepEqual(uniq(names(/\.createElement\(\s*(?!['"])([A-Za-z_]+)/g)), ['cfgTag', 'tag'], 'createElement(tag) in the builder; createElement(cfgTag) for a child card type from the card configuration');
  assert.deepEqual(uniq(names(/\.createElementNS\(\s*SVG_NS\s*,\s*(?!['"])([A-Za-z_]+)/g)), ['shapeTag']);
  assert.deepEqual(uniq(names(/\.setAttribute\(\s*(?!['"])([A-Za-z_]+)/g)), ['k'], 'setAttribute(k, v) only in the builder and the icon table');
  assert.deepEqual(uniq(names(/\.addEventListener\(\s*(?!['"])([A-Za-z_]+)/g)), ['type'], 'addEventListener(type, fn) only in the on() helper');
  assert.deepEqual(uniq(names(/\.removeAttribute\(\s*(?!['"])([A-Za-z_]+)/g)), []);
  assert.deepEqual(uniq(names(/\.createElement\(\s*'([^']+)'/g)), ['a'], 'the one literal element is the download anchor');
  // every attribute-name key written in an mk() attribute object is a quoted or bare literal (computed keys only for the two notice flags)
  assert.deepEqual(uniq(names(/\[(flag)\]:/g)), ['flag']);
});

test('inline style: only numeric --ecco-* custom properties are ever set from code', () => {
  const all = (code.match(/\.style\.setProperty\(/g) || []).length;
  const ok = (code.match(/\.style\.setProperty\(\s*'--ecco-[a-z]+'\s*,\s*String\(/g) || []).length;
  assert.equal(all, 2);
  assert.equal(ok, all);
  assert.deepEqual(uniq(names(/\.style\.(\w+)/g)), ['setProperty']);
});

test('hass: only hass.states, hass.locale and hass.themes are read, always by name, and the hass object is only handed to child cards', () => {
  assert.deepEqual(uniq(names(/\bhass\s*\.\s*(\w+)/g)), ['locale', 'states', 'themes']);
  assert.doesNotMatch(code, /\bhass\s*\[/);
  assert.doesNotMatch(code, /this\._hass\s*\./);
  assert.deepEqual(uniq(names(/\bhass\.locale\.(\w+)/g)), ['language']);
  assert.deepEqual(uniq(names(/\bhass\.themes\.(\w+)/g)), ['darkMode']);
  assert.equal((code.match(/\.hass\s*=\s*/g) || []).length, 2, 'child.hass = hass in the setter and when a late child is attached');
});

test('window and navigator: the only uses are the lifecycle listeners, the location path, the picker entry, the card helpers and the clipboard', () => {
  assert.deepEqual(uniq(names(/\bwindow\s*\.\s*(\w+)/g)), ['addEventListener', 'customCards', 'loadCardHelpers', 'location', 'removeEventListener']);
  assert.deepEqual(uniq(names(/\bwindow\.(?:add|remove)EventListener\(\s*'([^']+)'/g)), ['location-changed', 'pagehide']);
  assert.deepEqual(uniq(names(/\bnavigator\s*\.\s*(\w+)/g)), ['clipboard']);
  assert.deepEqual(uniq(names(/\bnavigator\.clipboard\.(\w+)/g)), ['writeText']);
  assert.deepEqual(uniq(names(/\bwindow\.location\.(\w+)/g)), ['pathname']);
});

test('events: exactly one event is dispatched, the standard hass-more-info, and it carries only an entity id', () => {
  assert.equal((code.match(/\bdispatchEvent\(/g) || []).length, 1);
  assert.deepEqual(names(/new CustomEvent\(\s*'([^']+)'/g), ['hass-more-info']);
  assert.match(code, /new CustomEvent\('hass-more-info', \{ bubbles: true, composed: true, detail: \{ entityId \} \}\)/);
});

test('timers: exactly one interval (the age tick), cleared on disconnect; no other timer', () => {
  assert.equal((code.match(/\bsetInterval\s*\(/g) || []).length, 1);
  assert.equal((code.match(/\bclearInterval\s*\(/g) || []).length, 1);
});

test('the mode: held by the controller closure only; no module-level mutable state; the controller never sees hass', () => {
  assert.equal((code.match(/\blet mode\b/g) || []).length, 1, 'one mutable mode, inside createModeController');
  assert.doesNotMatch(code, /^let /m, 'no module-level let');
  assert.doesNotMatch(code, /^var /m);
  const ctl = code.slice(code.indexOf('export function createModeController'), code.indexOf("if (typeof customElements !== 'undefined'"));
  assert.ok(ctl.length > 100 && ctl.length < 1200, 'the controller slice is the controller');
  assert.doesNotMatch(ctl, /hass|window|document|states/);
  assert.match(code, /get mode\(\) \{\s*return this\._ctl\.mode;\s*\}/);
  assert.doesNotMatch(code, /set mode\(/);
  assert.equal((code.match(/\._ctl\.set\(/g) || []).length, 3, 'the switch buttons, the key handler, the back-to-Production button and nothing else sets a mode');
});

test('one adapter, one derivation, one strip renderer, one summary: each is called from one place', () => {
  const calls = (name) => (code.match(new RegExp(`\\b${name}\\(`, 'g')) || []).length;
  assert.equal(calls('buildSnapshot'), 2, 'definition + the single call in _refresh');
  assert.equal(calls('deriveAlerts'), 2);
  assert.equal(calls('renderAlertStrip'), 2);
  assert.equal(calls('summarise'), 2);
});

test('no external resource: no URL, @import, url(), font-face, image, link or script in the module', () => {
  assert.doesNotMatch(src, /https?:\/\//);
  assert.doesNotMatch(src, /@import|(?<![A-Za-z])url\(|@font-face|<img|<link|<script|\bdata:/i);
});

test('the source is ASCII only, with no tab, no CR and no bidirectional or zero-width character (escapes are used instead)', () => {
  assert.doesNotMatch(src, /[^\x00-\x7f]/);
  assert.doesNotMatch(src, /\t/);
  assert.doesNotMatch(src, /\r/);
});

test('the exports exist', async () => {
  const mod = await import(cardUrl);
  for (const n of ['MODES', 'DEFAULT_MODE', 'WITHHELD', 'STATUSES', 'LIMITS', 'PALETTE', 'STYLE', 'TAG', 'VERSION', 'createModeController', 'buildSnapshot', 'deriveAlerts',
    'classifyRow', 'redactAttributes', 'redactValue', 'searchRows', 'windowRows', 'exportRows', 'validateCatalogue', 'validateChildCards', 'validateConfig',
    'cleanText', 'formatAge', 'summarise', 'catalogueItemIds', 'countWithheld', 'EccoModeShell']) {
    assert.ok(n in mod, `export ${n}`);
  }
  assert.equal(mod.TAG, 'ecco-mode-shell');
});

test('importing the module without a DOM registers nothing and does not throw', async () => {
  assert.equal(typeof globalThis.customElements, 'undefined');
  const mod = await import(`${cardUrl}?nodom`);
  assert.equal(typeof mod.EccoModeShell, 'function');
});

test('package.json: GPL-3.0-or-later, private, module, no dependency of any kind', () => {
  const pkg = JSON.parse(readFileSync(path.join(cardDir, 'package.json'), 'utf8'));
  assert.equal(pkg.license, 'GPL-3.0-or-later');
  assert.equal(pkg.private, true);
  assert.equal(pkg.type, 'module');
  assert.equal(pkg.name, 'ecco-mode-shell');
  assert.equal(pkg.scripts.test, 'node --test test/*.test.mjs');
  for (const k of ['dependencies', 'devDependencies', 'peerDependencies', 'optionalDependencies', 'bundledDependencies']) assert.equal(pkg[k], undefined, k);
});

test('the folder: text files only, LF only, no build output, lockfile or image', () => {
  const walk = (d) => readdirSync(d).flatMap((n) => (statSync(path.join(d, n)).isDirectory() ? walk(path.join(d, n)) : [path.join(d, n)]));
  const files = walk(cardDir);
  assert.ok(files.length >= 10);
  for (const f of files) {
    const b = readFileSync(f);
    assert.ok(!b.includes(0), `${f}: binary`);
    assert.ok(!b.includes(Buffer.from('\r\n')), `${f}: CRLF`);
    assert.doesNotMatch(path.basename(f), /\.(png|jpe?g|gif|webp|ico|woff2?|ttf|map)$|^package-lock\.json$/);
    assert.ok(!f.includes('node_modules'), f);
  }
});

test('the folder: no private layout, address, key block or personal identifier in any file (hostile secrets are assembled in code, never stored)', () => {
  const walk = (d) => readdirSync(d).flatMap((n) => (statSync(path.join(d, n)).isDirectory() ? walk(path.join(d, n)) : [path.join(d, n)]));
  for (const f of walk(cardDir)) {
    const t = readFileSync(f, 'utf8');
    assert.doesNotMatch(t, /\b(?:10|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}(?:\.\d{1,3})?\b/, `${f}: private address`);
    assert.doesNotMatch(t, /\b(?:[0-9a-f]{2}:){5}[0-9a-f]{2}\b/i, `${f}: MAC`);
    assert.doesNotMatch(t, /-----BEGIN [A-Z ]*KEY-----/, `${f}: key block`);
    assert.doesNotMatch(t, /\b(?:gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|xox[abprs]-[A-Za-z0-9-]{10,})/, `${f}: token`);
    // The one text that may look like an e-mail to this scan is the catalogue workstream's two connection-string decoys in noise.states.json
    // (scheme://synthetic:decoy@name.invalid): userinfo on a reserved .invalid host. They are exempt by that exact shape and nothing else is;
    // every other URL with userinfo, anywhere in the folder, still fails the credentials assertion below.
    const withoutDecoys = t.replace(/\b[a-z][a-z0-9+.-]*:\/\/synthetic:decoy@[a-z0-9.-]+\.invalid\b/g, '');
    assert.doesNotMatch(withoutDecoys, /\b[A-Za-z0-9._%+-]+@(?!users\.noreply\.github\.com)[A-Za-z0-9-]+\.[A-Za-z]{2,}\b/, `${f}: e-mail address`);
    assert.doesNotMatch(withoutDecoys, /[a-z][a-z0-9+.-]*:\/\/[^\s/@"']+@/i, `${f}: a URL with credentials`);
    assert.doesNotMatch(t, /[A-Za-z]:\\Users\\|\/Users\/[A-Za-z]/, `${f}: workstation path`);
  }
});

// ===========================================================================================================================
// Review round 1 ([r1])
// ===========================================================================================================================
// A reviewer mutant added `.shell[data-mode=geek] .alerts{display:none}` to the stylesheet and no test failed, because every AC6 test
// looked at the hidden ATTRIBUTE and the DOM position, never at the stylesheet. These tests read the stylesheet itself.
const { STYLE } = await import(cardUrl);

/**
 * A small CSS reader: every style rule as { selector, at, decls: [[property, value, spaced]] }, nested at-rules (media, container, keyframes) included.
 * `value` has all white space removed (the form most checks read); `spaced` keeps single spaces (the form the length checks read).
 */
function cssRules(css, at = []) {
  const out = [];
  let i = 0;
  while (i < css.length) {
    const open = css.indexOf('{', i);
    if (open === -1) break;
    let depth = 1;
    let j = open + 1;
    while (j < css.length && depth > 0) {
      if (css[j] === '{') depth += 1;
      else if (css[j] === '}') depth -= 1;
      j += 1;
    }
    const prelude = css.slice(i, open).replace(/\/\*[\s\S]*?\*\//g, '').trim();
    const body = css.slice(open + 1, j - 1);
    if (prelude.startsWith('@') || body.includes('{')) out.push(...cssRules(body, prelude.startsWith('@') ? [...at, prelude] : at));
    else {
      const decls = body.split(';').map((d) => d.trim()).filter(Boolean).map((d) => {
        const k = d.indexOf(':');
        const value = d.slice(k + 1).replace(/!important/i, '').trim().toLowerCase();
        return [d.slice(0, k).trim().toLowerCase(), value.replace(/\s+/g, ''), value.replace(/\s+/g, ' ')];
      });
      out.push({ selector: prelude.replace(/\s+/g, ' '), at, decls });
    }
    i = j;
  }
  return out;
}

// ---- lengths: a margin, an inset or a position offset can move the strip off the screen without hiding it in the CSS sense ([r2]) ----
const LENGTH = /^([+-]?(?:\d+\.?\d*|\.\d+))([a-z%]*)$/;
/** From this size a margin, inset or offset is no longer a gap but a displacement (per unit; any viewport or container unit and any percentage from 50). */
const BIG = Object.freeze({ px: 100, pt: 75, pc: 6, cm: 3, mm: 30, q: 120, in: 1.2, em: 8, rem: 8, ex: 16, ch: 8, lh: 8, rlh: 8, '%': 50 });
const hasOwnProp = (o, k) => Object.prototype.hasOwnProperty.call(o, k);
const bigFrom = (unit) => (hasOwnProp(BIG, unit) ? BIG[unit] : /^(?:[sld]?v|cq)(?:w|h|i|b|min|max)$/.test(unit) ? 50 : 0);
/** A function that cannot be judged without running the browser (so it is refused where a length decides whether the strip is on screen). */
const UNJUDGEABLE = /\b(?:var|calc|min|max|clamp|env|attr|round|mod|rem|abs|sign|anchor|anchor-size)\(/;
const OFFSET_PROP = /^(?:margin(?:-[a-z-]+)?|inset(?:-[a-z-]+)?|top|right|bottom|left|translate)$/;
const SIZE_PROP = /^(?:(?:min-|max-)?(?:width|height|inline-size|block-size))$/;

/** True when a list of lengths holds a negative one, a huge one, or something that cannot be judged: any of them can push an element off screen. */
function movesAway(text) {
  if (UNJUDGEABLE.test(text)) return true;
  for (const t of text.split(/[\s,/()]+/).filter(Boolean)) {
    const m = LENGTH.exec(t);
    if (!m) continue; // a keyword (auto, inherit, initial) or a function name
    const n = Number(m[1]);
    if (n === 0) continue;
    if (n < 0 || n >= bigFrom(m[2])) return true;
  }
  return false;
}

/** True when one length is small enough that an element clipped to it cannot show a line of text. */
function sliver(text) {
  if (UNJUDGEABLE.test(text)) return false;
  const m = LENGTH.exec(text.trim());
  if (!m) return false;
  const n = Number(m[1]);
  if (n === 0) return true;
  const limit = { px: 24, pt: 18, em: 1.5, rem: 1.5, ex: 3, ch: 2, lh: 1.5, rlh: 1.5, '%': 5 }[m[2]];
  return limit !== undefined ? n <= limit : /^(?:[sld]?v|cq)(?:w|h|i|b|min|max)$/.test(m[2]) && n <= 5;
}

/**
 * True when one declaration hides, collapses, clips, dims to nothing or moves off screen whatever it is applied to. `reaches` says the rule can apply
 * to the alert strip or to something that contains it (see reachesStrip): there a margin, an inset, a position offset or a translation of any size that
 * is negative, huge or unjudgeable is also a hiding declaration, and so is an animation (a keyframe could do any of the above).
 */
function hidingDeclaration(prop, v, reaches = false, spaced = v) {
  const num = (x) => Number.parseFloat(x);
  if (prop === 'display') return v === 'none' || (reaches && /var\(/.test(v));
  if (reaches && /var\(/.test(v) && (['visibility', 'content-visibility', 'opacity', 'transform', 'clip', 'clip-path', 'filter', 'scale', 'zoom'].includes(prop) || SIZE_PROP.test(prop) || OFFSET_PROP.test(prop))) return true;
  if (prop === 'visibility') return v === 'hidden' || v === 'collapse';
  if (prop === 'content-visibility') return v === 'hidden';
  if (prop === 'opacity') return num(v) <= 0.1;
  if (prop === 'filter') {
    const m = /opacity\(([^)]*)\)/.exec(v);
    return m !== null && (m[1].endsWith('%') ? num(m[1]) <= 10 : num(m[1]) <= 0.1);
  }
  if (prop === 'font-size') return num(v) === 0;
  if (prop === 'zoom') return num(v) === 0;
  if (prop === 'scale') return spaced.split(' ').some((t) => num(t) === 0);
  if (SIZE_PROP.test(prop) && !prop.startsWith('min-')) return /^0(px|em|rem|%|vh|vw)?$/.test(v) || (num(v) <= 1 && /^(\d+(\.\d+)?)px$/.test(v));
  if (prop === 'clip' || prop === 'clip-path') return v !== 'none' && v !== 'auto';
  if (prop === 'transform') {
    if (/scale(?:x|y|z)?\(0\)|scale(?:x|y|z)?\(0,|scale3d\(0/.test(v)) return true;
    return reaches && (/matrix(?:3d)?\(/.test(v) || [...spaced.matchAll(/translate(?:3d|x|y|z)?\(([^)]*)\)/g)].some((m) => movesAway(m[1])));
  }
  if (prop === 'z-index') return Number.parseInt(v, 10) < 0; // behind the opaque background of whatever sits under it: nothing in this stylesheet needs one
  if (prop === 'animation' || prop === 'animation-name') return reaches && v !== 'none' && !/^none\b/.test(v);
  if (reaches && OFFSET_PROP.test(prop)) return movesAway(spaced);
  if (['left', 'right', 'top', 'bottom', 'text-indent'].includes(prop)) return /^-\d{3,}/.test(v);
  if (prop === 'color' || prop === '-webkit-text-fill-color') return v === 'transparent';
  return false;
}

/** True when a rule clips (overflow hidden or clip) and also limits the height to a sliver: the content is there and cannot be seen. */
function clipsToSliver(decls) {
  const clips = decls.some(([p, v]) => /^overflow(?:-[xy])?$/.test(p) && /hidden|clip/.test(v));
  return clips && decls.some(([p, , sp]) => /^(?:max-)?(?:height|block-size)$/.test(p) && sliver(sp));
}

// Review round 3: both tokens now live in css-guard.mjs and are CASE-INSENSITIVE (an HTML attribute name in a selector is matched without regard to case, so
// [DATA-MODE=geek] is a mode selector), and the strip token also names the attributes the strip carries (role, aria-live, aria-label).
/** The only selectors that may name a mode: the switch thumb slides to the Geek side. Every one is a purely visual flourish of the switch. */
const MODE_SELECTORS = new Set(['.switch[data-mode="geek"] .thumb']);
/** The only selector allowed to hide anything: the standard [hidden] attribute rule. */
const HIDING_SELECTORS = new Set(['[hidden]']);
/** The only selectors allowed to NAME the alert strip or a part of it. A new one fails the test and needs a decision by whoever adds it. */
const STRIP_SELECTORS = new Set(['.alert', '.alert-action', '.alert-head', '.alert.quiet', '.alert.quiet>.ico', '.alert>.ico', '.alert[data-severity="critical"]',
  '.alert[data-severity="critical"]>.ico', '.alert[data-severity="warning"]', '.alert[data-severity="warning"]>.ico', '.alerts']);
/** Classes of the elements that contain the strip (the shell is its parent). */
const CONTAINER_CLASSES = new Set(['shell']);

/** A selector list split at the top-level commas only (a comma inside brackets, parentheses or quotes belongs to one selector). */
function splitSelectors(text) {
  const out = [];
  let depth = 0;
  let quote = null;
  let from = 0;
  for (let i = 0; i < text.length; i += 1) {
    const c = text[i];
    if (quote) {
      if (c === quote) quote = null;
    } else if (c === '"' || c === "'") quote = c;
    else if (c === '(' || c === '[') depth += 1;
    else if (c === ')' || c === ']') depth -= 1;
    else if (c === ',' && depth === 0) {
      out.push(text.slice(from, i).trim());
      from = i + 1;
    }
  }
  out.push(text.slice(from).trim());
  return out.filter(Boolean);
}

/** The last compound selector: what the rule is applied to (after the last descendant, child or sibling combinator outside brackets, parentheses and quotes). */
function lastCompound(sel) {
  let depth = 0;
  let quote = null;
  let from = 0;
  for (let i = 0; i < sel.length; i += 1) {
    const c = sel[i];
    if (quote) {
      if (c === quote) quote = null;
    } else if (c === '"' || c === "'") quote = c;
    else if (c === '(' || c === '[') depth += 1;
    else if (c === ')' || c === ']') depth -= 1;
    else if (depth === 0 && (c === ' ' || c === '>' || c === '+' || c === '~')) from = i + 1;
  }
  return sel.slice(from);
}

/**
 * True when a selector can apply to the alert strip or to an element that contains it: it names the strip, or what it is applied to has no class and no id
 * (a tag, *, an attribute or a bare pseudo-class such as :host), or it is the shell. A rule on a class the strip does not carry cannot reach it.
 */
function reachesStrip(sel) {
  if (ALERT_TOKEN.test(sel)) return true;
  const last = lastCompound(sel).replace(/\[[^\]]*\]/g, '').replace(/:{1,2}[a-z-]+(?:\([^)]*\))?/g, '');
  const classes = [...last.matchAll(/\.([A-Za-z0-9_-]+)/g)].map((m) => m[1]);
  if (classes.length === 0 && !/#[A-Za-z0-9_-]/.test(last)) return true;
  return classes.some((c) => CONTAINER_CLASSES.has(c));
}

const FORBIDDEN_PSEUDO = /:(?:has|is|where|matches|-webkit-any|-moz-any|first-child|last-child|only-child|nth-child|nth-last-child|first-of-type|last-of-type|only-of-type|nth-of-type|nth-last-of-type|empty)\b/;
/**
 * Selectors that pick an element out by what is around it or by whether it is hidden: :has(), :is(), :where(), a positional pseudo-class, the hidden
 * attribute (also inside :not()) and a sibling combinator. Whether such a rule hits the strip depends on the document, not on the rule, so no rule
 * but [hidden] may use one.
 */
function structuralProblems(sel) {
  const t = sel.replace(/"[^"]*"|'[^']*'/g, '""');
  const out = [];
  if (FORBIDDEN_PSEUDO.test(t)) out.push('a selector with :has(), :is(), :where() or a positional pseudo-class');
  if (/\[\s*hidden\b|:not\([^)]*hidden/.test(t)) out.push('a selector that depends on the hidden attribute');
  if (/[+~]/.test(t.replace(/\[[^\]]*\]/g, ''))) out.push('a selector with a sibling combinator');
  return out;
}

/** Every way a stylesheet could hide, shift or clip the alert strip (or anything else) in a mode. [] when it cannot. */
function cssViolations(css) {
  const bad = [];
  for (const r of cssRules(css)) {
    const keyframes = r.at.some((a) => /^@(?:-webkit-)?keyframes/i.test(a));
    for (const s of splitSelectors(r.selector)) {
      const reaches = keyframes || reachesStrip(s);
      const hides = r.decls.filter(([p, v, sp]) => hidingDeclaration(p, v, reaches, sp)).map(([p, v]) => `${p}:${v}`);
      if (reaches && clipsToSliver(r.decls)) hides.push('overflow clips a sliver of height');
      if (MODE_TOKEN.test(s) && !MODE_SELECTORS.has(s)) bad.push(`mode-dependent selector: ${s}`);
      if (ALERT_TOKEN.test(s) && !STRIP_SELECTORS.has(s)) bad.push(`a selector names the alert strip and is not on the pinned list: ${s}`);
      if (ALERT_TOKEN.test(s) && hides.length) bad.push(`hiding declaration on the alert strip: ${s} { ${hides.join('; ')} }`);
      if (hides.length && !HIDING_SELECTORS.has(s)) bad.push(`hiding declaration outside [hidden]: ${s} { ${hides.join('; ')} }`);
      if (!HIDING_SELECTORS.has(s)) for (const why of structuralProblems(s)) bad.push(`${why} outside [hidden]: ${s}`);
    }
  }
  return [...new Set(bad)];
}

test('AC6 [r1] the stylesheet cannot hide the alert strip in either mode: no mode-dependent selector except the switch thumb, no hiding declaration except the [hidden] rule', () => {
  const rules = cssRules(STYLE);
  assert.ok(rules.length > 120, `the reader found ${rules.length} rules`);
  assert.ok(rules.some((r) => r.selector === '.alerts') && rules.some((r) => r.selector === '.alert'), 'the reader sees the strip rules');
  assert.ok(rules.some((r) => r.selector === '[hidden]' && r.decls.some(([p, v]) => p === 'display' && v === 'none')), 'and the [hidden] rule');
  assert.ok(rules.some((r) => r.selector === '.switch[data-mode="geek"] .thumb'), 'and the one mode selector');
  assert.deepEqual(cssViolations(STYLE), []);
  // exactly the declared mode selectors and nothing else name a mode
  const named = [...new Set(rules.flatMap((r) => r.selector.split(',').map((s) => s.trim())).filter((s) => MODE_TOKEN.test(s)))];
  assert.deepEqual(named, ['.switch[data-mode="geek"] .thumb']);
});

test('AC6 [r1] the stylesheet reader has teeth: each way of hiding the strip, in either mode, is reported (negative controls)', () => {
  const geek = '.shell[data-mode="geek"]';
  const evil = [
    `${geek} .alerts{display:none}`,
    `${geek} .alerts{visibility:hidden}`,
    `${geek} [data-ecco-alert-strip]{opacity:0}`,
    `${geek} .alert{height:0;overflow:hidden}`,
    `${geek} .alerts{clip-path:inset(100%)}`,
    `${geek} .alerts{position:absolute;left:-9999px}`,
    `${geek} .alerts{font-size:0}`,
    `${geek} .alerts{color:transparent}`,
    `${geek} .alerts{transform:scale(0)}`,
    `[data-ecco-body="geek"] ~ .alerts{display:none}`,
    `.shell:has([data-ecco-body="geek"]:not([hidden])) .alerts{display:none}`,
    `.shell[data-mode="geek"]{display:none}`,
    `.alerts{display:none}`,
    `.alert{opacity:0}`,
    `.alerts{max-height:0}`,
    `@media (min-width:1px){.alerts{display:none}}`,
    `@container (max-width:9999px){${geek} .alerts{display:none}}`,
    `@media (prefers-color-scheme: dark){.alerts{visibility:hidden}}`,
    `.shell[data-theme="dark"] .alerts{display:none}`,
    `.alerts[hidden]{display:none}`,
    `[data-ecco-alert-strip]{display:none!important}`,
    `.alerts{content-visibility:hidden}`,
    `.alerts, .other{display:none}`,
    `.x{width:0} ${geek} .alerts{display:none}`,
  ];
  for (const css of evil) assert.notDeepEqual(cssViolations(css), [], `not caught: ${css}`);
  // a hostile rule appended to the real stylesheet is caught too (the reviewer's own mutant)
  for (const css of evil) assert.notDeepEqual(cssViolations(`${STYLE}\n${css}`), [], `not caught when appended: ${css}`);
  // harmless rules pass
  for (const css of ['.switch[data-mode="geek"] .thumb{transform:translateX(100%)}', '[hidden]{display:none!important}', '.alert{display:grid;border:1px solid red}', '.btn:disabled{opacity:.55}',
    '@media (prefers-reduced-motion: reduce){*{animation:none!important}}', '.alerts{display:grid;gap:8px;min-width:0}', '.alert.quiet{border-left-color:var(--ecco-live)}', '.shell[data-theme="dark"]{--x:1}']) {
    assert.deepEqual(cssViolations(css), [], css);
  }
});

// ---------------------------------------------------------------------------------------------------------------------------
// Review round 2 ([r2]). The reviewer's mutant R2-16 added `.shell:has(> .region:last-child:not([hidden])) .alerts{margin-left:-200vw}`: the Geek body is the
// last .region, so the strip left the screen in Geek Mode only, and every suite passed (the selector has no mode token and margin was not a hiding
// declaration). Three layers now: (1) the selectors that may NAME the strip are pinned; (2) no rule but [hidden] may use :has(), :is(), :where(), a
// positional pseudo-class, the hidden attribute or a sibling combinator; (3) a rule that can reach the strip (names it, contains it, or has no class to
// tell it apart) may not carry a margin, inset, offset or translation that is negative, huge or unjudgeable, a negative z-index, an animation, or an
// overflow clip on a sliver of height.
// ---------------------------------------------------------------------------------------------------------------------------
const violationText = (css) => cssViolations(css).join('\n');

test('AC6 [r2] exactly the pinned selectors name the alert strip or a part of it, and the stylesheet uses all of them', () => {
  const named = [...new Set(cssRules(STYLE).flatMap((r) => splitSelectors(r.selector)).filter((s) => ALERT_TOKEN.test(s)))].sort();
  assert.deepEqual(named, [...STRIP_SELECTORS].sort(), 'the pinned list is neither longer nor shorter than what the stylesheet uses');
  assert.ok(STRIP_SELECTORS.has('.alerts') && STRIP_SELECTORS.has('.alert'));
  // a new selector that names the strip, however harmless its declarations, is a decision for a person: it fails here
  for (const css of ['.shell .alerts{gap:2px}', '.alerts::before{content:"x"}', '.alerts:focus-within{outline:1px solid red}', '.alert-new{color:red}', '[data-ecco-alert-strip]{gap:2px}',
    '.alerts.compact{gap:2px}', '.alert>.new{color:red}', '.alert[data-severity="info"]{color:red}']) {
    assert.match(violationText(css), /not on the pinned list/, css);
    assert.match(violationText(`${STYLE}\n${css}`), /not on the pinned list/, `when appended: ${css}`);
  }
  // the pinned selectors themselves carry no hiding, shifting or clipping declaration (checked as strip rules, which is the strictest reading)
  for (const r of cssRules(STYLE).filter((x) => splitSelectors(x.selector).some((s) => STRIP_SELECTORS.has(s)))) {
    assert.deepEqual(r.decls.filter(([p, v, sp]) => hidingDeclaration(p, v, true, sp)), [], r.selector);
    assert.equal(clipsToSliver(r.decls), false, r.selector);
  }
});

test('AC6 [r2] which rules can reach the strip: the strip, the shell and anything without a class do; a rule on another class cannot', () => {
  for (const s of ['.alerts', '.alert', '.alert-head', '.alert>.ico', '[data-ecco-alert-strip]', '.shell', '.shell[data-theme="dark"]', '.shell:not([data-theme="light"])', ':host', '*', '*::before',
    'div', 'span', '.healthbar>span', '.shell>*', '.shell>div', '[role="region"]', '[data-status="LIVE"]', ':focus-visible', '.x>:last-child']) assert.equal(reachesStrip(s), true, s);
  for (const s of ['.row', '.mode-note', '.search>.ico', '.tile .ring', '.ring::after', '.btn:disabled', '.opt[aria-checked="true"]', '.switch[data-mode="geek"] .thumb']) {
    assert.equal(reachesStrip(s), false, s);
  }
  const rules = cssRules(STYLE);
  assert.ok(rules.filter((r) => splitSelectors(r.selector).some(reachesStrip)).length >= 20, 'a good share of the real rules is checked as reaching');
  // none of the rules that reach the strip in the real stylesheet shifts anything
  for (const r of rules) {
    if (!splitSelectors(r.selector).some(reachesStrip)) continue;
    for (const [p, , sp] of r.decls) if (/^(?:margin|inset|top|right|bottom|left|translate)/.test(p)) assert.equal(movesAway(sp), false, `${r.selector} { ${p}: ${sp} }`);
  }
});

test('AC6 [r2] the stylesheet reader catches a strip that is shifted, clipped or picked out by position, and the reviewer mutant R2-16 itself (negative controls)', () => {
  const r216 = '.shell:has(> .region:last-child:not([hidden])) .alerts{margin-left:-200vw}';
  // R2-16 is caught three times over: the selector names the strip without being pinned, it uses :has() and a positional pseudo-class and the hidden attribute,
  // and the margin is a displacement
  const t = violationText(r216);
  assert.match(t, /not on the pinned list/);
  assert.match(t, /:has\(\)/);
  assert.match(t, /depends on the hidden attribute/);
  assert.match(t, /hiding declaration on the alert strip: .*margin-left:-200vw/);
  assert.match(violationText(`${STYLE}\n${r216}`), /margin-left:-200vw/);
  const evil = [
    r216,
    // the strip's own selectors are pinned, so the declaration has to be judged
    '.alerts{margin-left:-200vw}', '.alerts{margin-left:-1px}', '.alert{margin-top:-9999px}', '.alerts{margin:0 0 0 100vw}', '.alerts{margin-inline-start:-50%}',
    '.alerts{position:relative;left:-30px}', '.alerts{position:absolute;top:99999px}', '.alerts{inset:0 0 0 -500px}', '.alerts{inset-inline-start:120vw}', '.alert{translate:-100vw 0}',
    '.alerts{transform:translateX(-120%)}', '.alerts{transform:translate3d(0,-9999px,0)}', '.alerts{transform:matrix(1,0,0,1,-5000,0)}',
    '.alerts{margin-left:calc(-1 * var(--x))}', '.alerts{margin-left:var(--gap)}', '.alerts{display:var(--none)}', '.alerts{opacity:var(--o)}',
    '.alerts{z-index:-1}', '.alerts{height:2px;overflow:hidden}', '.alert{max-height:12px;overflow-y:clip}', '.alerts{block-size:0}', '.alerts{max-inline-size:0}',
    '.alerts{scale:0}', '.alerts{zoom:0}', '.alerts{filter:opacity(0)}', '.alerts{filter:opacity(5%)}', '.alerts{animation:ecco-away 1s forwards}', '@keyframes ecco-away{to{margin-left:-200vw}}',
    '@keyframes ecco-away{to{display:none}}',
    // generic selectors reach the strip without naming it
    '.shell>*{margin-left:-200vw}', 'div{margin-top:-9999px}', '[role="region"]{left:-300px;position:absolute}', '.shell{margin-left:-200vw}', '.shell{translate:-100vw}',
    ':host{position:relative;left:-100vw}', '*{height:0;overflow:hidden}', '.shell>*{height:3px;overflow:hidden}', '[aria-live]{inset-inline-start:-80vw}',
    // harmless declarations, but the selector picks the strip out by its position or by what surrounds it
    '.shell>.region:last-child~.alerts{color:red}', '.shell>:nth-child(3){color:red}', '.shell>div:last-child{color:red}', '.shell>div:nth-of-type(2){color:red}',
    '.shell:has(.x){color:red}', ':is(.alerts,.x){color:red}', ':where(.alerts){color:red}', '.region:first-child{color:red}', '.x:not([hidden]){color:red}',
    '.region[hidden]~div{color:red}', '.x+.y{color:red}', '.x:empty{color:red}', '.x:only-child{color:red}', '.x:nth-last-child(1){color:red}', '.x:last-of-type{color:red}',
    '.x:not(.a,.b[hidden]){color:red}', '.x:-webkit-any(.a){color:red}',
    // a hiding declaration anywhere outside [hidden]
    '.x{z-index:-1}', '.x{block-size:0}', '.x{filter:opacity(0)}', '.x{scale:0 1}',
  ];
  for (const css of evil) {
    assert.notDeepEqual(cssViolations(css), [], `not caught: ${css}`);
    assert.notDeepEqual(cssViolations(`${STYLE}\n${css}`), [], `not caught when appended: ${css}`);
  }
  // harmless rules still pass (several are the real stylesheet's own: a negative margin, offsets, a z-index, a clip, an animation, an attribute-only selector)
  const harmless = ['.row{margin-left:12px}', '.mode-note{margin:-6px 0 0}', '.search>.ico{position:absolute;left:12px;top:13px}', '.thumb{position:absolute;top:4px;bottom:4px;left:4px}',
    '.opt{position:relative;z-index:1}', '.ring::after{inset:5px}', '.healthbar{display:flex;height:10px;overflow:hidden}', '.raw{max-height:320px;overflow:auto}', '.alerts{margin:0}',
    '.alert{margin:8px 0 0;padding:4px}', '.alert{overflow:hidden;min-height:44px}', '.shell{gap:12px;margin:0 auto}', '*,*::before,*::after{animation:none!important}',
    '@keyframes ecco-pulse{0%,100%{box-shadow:none}50%{box-shadow:0 0 14px 2px red}}', '.shell:not([data-theme="light"]){--x:1}', '.tile .ring{animation:ecco-pulse 3s}',
    '[data-status-chip="STALE"]{border-style:dashed}', ':focus-visible{outline:3px solid red;outline-offset:2px}', '.shell{display:grid;gap:12px;min-width:0}'];
  for (const css of harmless) assert.deepEqual(cssViolations(css), [], css);
});

test('AC6 [r2] the length reader: negative, huge and unjudgeable values move things away; zero, small and keyword values do not', () => {
  for (const v of ['-1px', '-200vw', '0 0 0 100vw', '120%', '100px', '8rem', '-0.5em', 'calc(1px + 1px)', 'var(--x)', 'min(1px, 2px)', '50vh', '50cqw', '3cm']) assert.equal(movesAway(v), true, v);
  for (const v of ['0', '0 auto', 'auto', '8px 0 0', '12px', '49%', '4rem', '1.5em', '24px', 'inherit', '0 0 0 0', '99px']) assert.equal(movesAway(v), false, v);
  for (const v of ['0', '2px', '24px', '1.5em', '5%', '5vh']) assert.equal(sliver(v), true, v);
  for (const v of ['25px', '2em', '10%', '40px', 'auto', 'calc(1px)', '50vh']) assert.equal(sliver(v), false, v);
});

test('AC6 [r1] the alert strip rules never mention a mode, a body or a hidden state, and the strip has no attribute that could hide it', () => {
  assert.doesNotMatch(src, /ui\.strip\.hidden|strip\.setAttribute\('hidden'|strip\.style\./);
  assert.doesNotMatch(src, /\.alerts[^{]*\[hidden\]/);
  const strip = cssRules(STYLE).filter((r) => ALERT_TOKEN.test(r.selector));
  assert.ok(strip.length >= 8);
  for (const r of strip) assert.ok(!MODE_TOKEN.test(r.selector), r.selector);
});

test('AC16 [r1] opening an entity: one guard function decides, and it guards both the row control and the dispatch', async () => {
  const mod = await import(cardUrl);
  assert.equal(typeof mod.canOpenMoreInfo, 'function');
  assert.deepEqual([...mod.MORE_INFO_DOMAINS].sort(), ['binary_sensor', 'event', 'sensor']);
  assert.match(code, /_openEntity\(entityId\) \{\s*if \(!canOpenMoreInfo\(entityId\)\) return;/);
  assert.ok((code.match(/\bcanOpenMoreInfo\(/g) || []).length >= 3, 'definition, the dispatch guard and the row control');
});

test('AC3 [r1] setConfig resets the mode first (Home Assistant keeps the element when the dashboard configuration changes)', () => {
  assert.match(code, /setConfig\(config\) \{\s*this\._ctl\.reset\(\);/);
});

test('AC12 [r1] the update pump: one timer slot, one setInterval and one clearInterval, started and stopped only through the two slot functions', () => {
  assert.match(code, /_startTimer\(ms\) \{[\s\S]*?setInterval\(/);
  assert.match(code, /_stopTimer\(\) \{[\s\S]*?clearInterval\(/);
  assert.equal((code.match(/\._startTimer\(/g) || []).length >= 2, true);
  assert.doesNotMatch(code, /\bsetTimeout\s*\(/);
});

// ---------------------------------------------------------------------------------------------------------------------------
// Review round 3 ([r3]). Rounds 1 and 2 grew a LIST OF WAYS to hide the strip, and each round the reviewer found one more: [DATA-MODE=geek] (attribute names
// are case-insensitive), [role=region] and [aria-live] (the strip is also picked out by attributes), rotateX, a tiny font-size, scale(.001), a transparent
// rgba colour, a blur filter and order. This section stops extending the list. Three nets that do not ask "is this a known way to hide it":
//   1. the PIN: every rule, selector and declaration of the stylesheet is in test/fixtures/style.pin.json; a new or changed one fails until a person
//      regenerates the file in a reviewed diff (test/style-pin.mjs prints it);
//   2. the ALLOWLIST: a rule that can reach the strip (it, what contains it, what it contains) may set only the properties on STRIP_ALLOWLIST, each with a
//      bounded value; a property that is not on the list is refused whatever it does;
//   3. the READER: it refuses what it cannot judge (a CSS escape, a comment, an @import, an at-rule or condition nobody pinned, a nested rule).
// The headless-Chrome check (preview/check-strip.mjs) is a fourth net that does not read the stylesheet at all.
// ---------------------------------------------------------------------------------------------------------------------------
const PIN = JSON.parse(readFileSync(path.join(cardDir, 'test', 'fixtures', 'style.pin.json'), 'utf8'));
/** Every net that reads CSS text, in one list of reasons ([] when the stylesheet is acceptable): the round-one and round-two checks and the allowlist. */
const strictAll = (css) => [...cssViolations(css), ...stripProblems(css, { modeSelectors: MODE_SELECTORS, stripSelectors: STRIP_SELECTORS })];
/** Both nets together: the semantic reader and the pin. */
const nets = (css) => ({ semantic: strictAll(css), pin: pinProblems(css, PIN) });

test('AC6 [r3] the whole stylesheet is pinned: every rule, selector and declaration is the one a person approved (regenerate the pin only after reading the new rule)', () => {
  assert.equal(PIN.schema, 'ecco-mode-shell-style-pin/1');
  assert.ok(Array.isArray(PIN.rules) && PIN.rules.length > 120, `the pin lists ${PIN.rules.length} rules`);
  const read = parseSheet(STYLE);
  assert.deepEqual(read.problems, [], 'the reader understands the whole stylesheet');
  assert.deepEqual(pinProblems(STYLE, PIN), [], 'the stylesheet is the pinned one: a new or changed rule needs a person to regenerate test/fixtures/style.pin.json (node test/style-pin.mjs) and review its diff');
});

test('AC6 [r3] the pin has teeth: a new selector, a new or changed declaration, a removed, moved or re-conditioned rule, anywhere, is reported', () => {
  const base = STYLE;
  const edits = {
    'a new rule with a harmless selector and declaration': `${base}\n.zz{color:red}`,
    'a new selector on an existing rule': base.replace('.alerts{display:grid;gap:8px;min-width:0}', '.alerts,.zz{display:grid;gap:8px;min-width:0}'),
    'a new declaration on an existing rule': base.replace('.alert-head{font-weight:700}', '.alert-head{font-weight:700;letter-spacing:.1px}'),
    'a changed value (one digit)': base.replace('.alert-head{font-weight:700}', '.alert-head{font-weight:600}'),
    'a changed colour': base.replace('--ecco-live:#13693b', '--ecco-live:#13693c'),
    'a changed length': base.replace('.alerts{display:grid;gap:8px;min-width:0}', '.alerts{display:grid;gap:9px;min-width:0}'),
    'a removed declaration': base.replace('.alert-head{font-weight:700}', '.alert-head{}'),
    'a removed rule': base.replace('.alert-head{font-weight:700}\n', ''),
    'a changed media condition': base.replace('@media (prefers-color-scheme: dark)', '@media (prefers-color-scheme: light)'),
    'a changed container condition': base.replace('@container (max-width:560px)', '@container (max-width:561px)'),
    'a declaration moved into another rule': base.replace('.alert-head{font-weight:700}', '.alert-head{}').replace('.alert-action{margin:0;', '.alert-action{font-weight:700;margin:0;'),
    '!important added': base.replace('.alert-head{font-weight:700}', '.alert-head{font-weight:700!important}'),
    'a property name in another case that is a new property': `${base}\n.alert-head{LETTER-SPACING:1px}`,
  };
  for (const [what, css] of Object.entries(edits)) {
    assert.notEqual(css, base, `the edit changed nothing: ${what}`);
    assert.notDeepEqual(pinProblems(css, PIN), [], `not caught: ${what}`);
  }
  // two adjacent rules swapped: the cascade changes
  const rules = base.split('\n');
  const i = rules.findIndex((l) => l.startsWith('.alert-head{'));
  const swapped = [...rules];
  [swapped[i], swapped[i + 1]] = [swapped[i + 1], swapped[i]];
  assert.notDeepEqual(pinProblems(swapped.join('\n'), PIN), [], 'rules in another order');
  // formatting is free: white space, a trailing semicolon and the case of a property name change nothing
  assert.deepEqual(pinProblems(base.replace('.alert-head{font-weight:700}', '.alert-head  {  FONT-WEIGHT : 700 ;  }'), PIN), []);
  assert.deepEqual(pinProblems(`\n\n${base}\n\n`, PIN), []);
  // every report names the rule, so a reviewer can act on it
  assert.match(pinProblems(edits['a changed value (one digit)'], PIN).join('\n'), /alert-head/);
});

test('AC6 [r3] the reader refuses what it cannot judge: escapes, comments, @import and other at-rules, an unpinned condition, nested rules, unbalanced or stray text', () => {
  assert.deepEqual(parseSheet(STYLE).problems, []);
  const unreadable = [
    '.alerts{d\\isplay:none}', '.al\\65rts{display:none}', '.alerts{display:\\6eone}', '.alerts{display/**/:none}', '.alerts{display:none/**/}', '/**/.alerts{display:none}',
    '.al/**/erts{display:none}', '<!-- .alerts{display:none}', '.alerts{display:none} -->',
    '@import "x.css";.alerts{display:none}', '@import url(x.css);', '@charset "utf-8";', '@namespace svg "x";', '@font-face{font-family:x}', '@supports (display:grid){.alerts{display:none}}',
    '@layer x{.alerts{display:none}}', '@scope (.shell){.alerts{display:none}}', '@page{margin:0}', '@property --x{syntax:"<length>";inherits:false;initial-value:0px}',
    '@media (min-width:1px){.alerts{display:none}}', '@media screen{.alerts{display:none}}', '@container (min-width:1px){.alerts{display:none}}', '@media (prefers-color-scheme: dark) and (min-width:1px){.x{color:red}}',
    '@keyframes evil{to{display:none}}', '@-webkit-keyframes ecco-pulse{to{box-shadow:none}}',
    '@media (prefers-color-scheme: dark){@media (min-width:1px){.x{color:red}}}', '@media (prefers-reduced-motion: reduce){@container (min-width:561px){.x{color:red}}}',
    '.shell{.alerts{display:none}}', '.shell{&>[aria-live]{display:none}}', '.shell{& .alerts{display:none}}', '.x{color:red;.y{color:blue}}', '&.alerts{display:none}',
    '.alerts{display:none', '.alerts display:none}', '.alerts{display}', '.alerts{:none}', '.alerts{di splay:none}', '.alerts{display:}', '}', '.alerts{display:none}}', 'a;b{color:red}',
    '.alerts{display:none}\u0000', '{color:red}',
  ];
  for (const css of unreadable) {
    assert.notDeepEqual(parseSheet(css).problems, [], `the reader accepted: ${JSON.stringify(css)}`);
    assert.notDeepEqual(parseSheet(`${STYLE}\n${css}`).problems, [], `the reader accepted it appended: ${JSON.stringify(css)}`);
    assert.notDeepEqual(strictAll(`${STYLE}\n${css}`), [], `a stylesheet with it passes the strict net: ${JSON.stringify(css)}`);
    assert.notDeepEqual(pinProblems(`${STYLE}\n${css}`, PIN), [], `a stylesheet with it passes the pin: ${JSON.stringify(css)}`);
  }
  // things that LOOK odd but are plain CSS this reader understands (quotes and brackets protect their contents)
  for (const css of ['.x::after{content:"}"}', '.x[data-a="a;b"]{color:red}', '.x{font-family:"A, B",Arial}', '.x{background:url(a;b)}', '.x:nth-child(2n+1){color:red}']) {
    assert.deepEqual(parseSheet(css).problems, [], css);
  }
});

test('AC6 [r3] the mode and strip tokens are case-insensitive, and the strip token also names the attributes the strip carries', () => {
  for (const s of ['.shell[DATA-MODE="geek"]', '.shell[Data-Mode=geek]', '[DATA-ECCO-BODY=geek]', '[data-ecco-body=GEEK]', '.shell[data-mode="GEEK" i]', '[data-geek]', '[DATA-PRODUCTION]', '.geek', '.Production .x',
    '[data-ecco-mode]', '.shell[*|DATA-MODE=geek]']) assert.match(s, MODE_TOKEN, s);
  for (const s of ['.shell', '.opt[aria-checked="true"]', '.btn[aria-pressed="true"]', '.production-ish', '.geeky', '[data-status="LIVE"]']) assert.doesNotMatch(s, MODE_TOKEN, s);
  for (const s of ['.alerts', '.ALERTS', '.Alert', '.alert-head', '[DATA-ECCO-ALERT-STRIP]', '[Data-Alert-Id]', '[data-severity=critical]', '[role=region]', '[ROLE=alert]', '[Role="status"]', '[aria-live]', '[ARIA-LIVE=polite]',
    '[aria-label^="Safety"]', '[aria-atomic]', '[aria-relevant]', '[*|role]', 'div[role=region]', '.shell>[role=region]', '[role|=region]']) assert.match(s, ALERT_TOKEN, s);
  for (const s of ['.opt[aria-checked="true"]', '.btn[aria-pressed="true"]', '.gbtn[aria-expanded="false"] .ico', '.row', '[data-status="LIVE"]', '[hidden]']) assert.doesNotMatch(s, ALERT_TOKEN, s);
  // the old case-sensitive check let these through: they are reported now
  assert.match(violationText('.shell[DATA-MODE="geek"]>.x{color:red}'), /mode-dependent selector/);
  assert.match(violationText('.shell[Data-Ecco-Body=geek] .x{color:red}'), /mode-dependent selector/);
  assert.match(violationText('[ROLE=region]{color:red}'), /not on the pinned list/);
  assert.match(violationText('[Aria-Live]{color:red}'), /not on the pinned list/);
  assert.match(violationText('.ALERTS{color:red}'), /not on the pinned list/);
  assert.match(violationText('.shell[DATA-MODE="geek"] .thumb{color:red}'), /mode-dependent selector/, 'the pinned thumb selector is matched by its exact text only');
});

test('AC6 [r3] which rules can reach the strip, read strictly: only a class the strip and its neighbours cannot carry rules a selector out', () => {
  for (const s of ['.alerts', '.alert', '.alert-head', '.alert>.ico', '.alert.quiet>.ico', '.shell', '.shell[data-theme="dark"]', ':host', '*', '*::before', 'div', 'span', 'svg', '[role="region"]', '[aria-live]',
    '[data-status="LIVE"]', ':focus-visible', '.shell>*', '.shell>div', '.shell .alerts', 'div[aria-live]', '.ico', '.shell::before', '[class~=alerts]', '[class*=lert]', '.shell>[role=region]']) assert.equal(reachesStripStrict(s), true, s);
  for (const s of ['.row', '.mode-note', '.search>.ico', '.tile .ring', '.ring::after', '.btn:disabled', '.opt[aria-checked="true"]', '.switch[data-mode="geek"] .thumb', '.healthbar>span',
    '.healthbar>[data-seg="STALE"]', '.chip>.ico', '.gbtn .ico', '.count>.ico', '.panel .tile', '#x', '.row *', '.region .x', '.summary small']) assert.equal(reachesStripStrict(s), false, s);
  assert.deepEqual(compounds('.shell>.alerts .alert:not(.x)[a="b c"]'), ['.shell', '.alerts', '.alert:not(.x)[a="b c"]']);
  const rules = parseSheet(STYLE).rules.filter((r) => !r.keyframes);
  const reaching = rules.filter((r) => r.selectors.some(reachesStripStrict));
  assert.ok(reaching.length >= 25 && reaching.length <= 40, `${reaching.length} rules of the real stylesheet can reach the strip`);
  // none of them uses a property the allowlist does not know (the real stylesheet is inside its own allowlist)
  for (const r of reaching) {
    if (r.selectors.length === 1 && r.selectors[0] === '[hidden]') continue;
    for (const d of r.decls) assert.ok(d.prop.startsWith('--') || d.prop === 'width' || d.prop === 'height' || Object.prototype.hasOwnProperty.call(STRIP_ALLOWLIST, d.prop), `${r.selectors[0]}: ${d.prop}`);
  }
});

test('AC6 [r3] the real stylesheet passes every net, and the allowlist has no property that can hide, shift, clip, shrink or fade the strip', () => {
  assert.deepEqual(strictAll(STYLE), []);
  assert.deepEqual(cssViolations(STYLE), []);
  assert.ok(THEME_VARS.has('--ecco-surface') && THEME_VARS.has('--ecco-fg') && THEME_VARS.size === 15);
  for (const p of ['transform', 'rotate', 'scale', 'translate', 'perspective', 'filter', 'backdrop-filter', 'opacity', 'clip', 'clip-path', 'mask', 'mask-image', '-webkit-mask', '-webkit-mask-image', 'mask-clip',
    'visibility', 'content-visibility', 'contain', 'contain-intrinsic-size', 'position', 'inset', 'inset-inline-start', 'top', 'left', 'right', 'bottom', 'z-index', 'order', 'line-height', 'height', 'width', 'max-height',
    'min-height', 'block-size', 'inline-size', 'overflow', 'overflow-x', 'overflow-y', 'text-indent', 'letter-spacing', 'word-spacing', 'white-space', 'text-overflow', 'pointer-events', 'zoom', 'content', 'mix-blend-mode',
    'isolation', 'will-change', 'writing-mode', 'direction', 'text-shadow', '-webkit-text-fill-color', '-webkit-line-clamp', 'appearance', 'float', 'clear', 'vertical-align', 'all', 'float', 'text-transform',
    'font-variant', 'font-stretch', 'text-decoration', 'transform-origin', 'offset-path', 'anchor-name', 'view-transition-name', 'animation-name', 'animation-duration', 'transition-property', 'box-shadow', 'object-fit',
    'resize', 'cursor', 'user-select', 'visibility', 'text-size-adjust', 'hyphens', 'tab-size', 'column-count', 'columns', 'grid-template-rows', 'grid-auto-flow', 'justify-content', 'place-items', 'align-self']) {
    assert.equal(Object.prototype.hasOwnProperty.call(STRIP_ALLOWLIST, p), false, `${p} must not be allowlisted for a rule that reaches the strip`);
  }
  // and the properties that ARE on it carry bounded values
  const rule = (decl) => `.alerts{${decl}}`;
  for (const [decl, why] of [['font-size:.01px', 'a font that cannot be read'], ['font-size:11px', 'below 12 px'], ['font-size:1px', ''], ['padding:100px', 'a huge padding'], ['margin:30px', 'a big margin'],
    ['margin:-1px', 'a negative margin'], ['gap:100px', 'a huge gap'], ['color:rgba(0,0,0,0)', 'transparent text'], ['color:rgba(0,0,0,.3)', 'faint text'], ['background:rgba(0,0,0,0)', 'a clear background'],
    ['color:transparent', ''], ['color:#0000', ''], ['color:#00000000', ''], ['background:transparent', ''], ['border-left-color:rgba(0,0,0,0)', ''], ['display:none', ''], ['display:contents', ''],
    ['min-width:100vw', ''], ['max-width:0', ''], ['grid-template-columns:0 1fr', ''], ['grid-template-columns:minmax(0,0fr)', ''], ['animation:x 1s', ''], ['transition:all 1s', ''],
    ['font:1px/1 Arial', ''], ['font:14px/0 Arial', ''], ['font-weight:1', ''], ['border:20px solid red', ''], ['outline:40px solid red', ''], ['border-radius:5000px', '']]) {
    assert.notDeepEqual(stripProblems(rule(decl), { modeSelectors: MODE_SELECTORS, stripSelectors: STRIP_SELECTORS }), [], `${decl} ${why}`);
  }
  for (const [decl] of [['font-size:.9rem'], ['font-size:14px'], ['padding:4px 10px'], ['margin:0'], ['gap:2px 10px'], ['color:#102030'], ['color:var(--ecco-fg2)'], ['background:var(--ecco-surface)'],
    ['display:grid'], ['border:1px solid var(--ecco-line)'], ['border-left:6px solid var(--ecco-accent)'], ['border-radius:12px'], ['grid-template-columns:auto minmax(0,1fr)'], ['font-weight:700']]) {
    assert.deepEqual(stripProblems(rule(decl), { modeSelectors: MODE_SELECTORS, stripSelectors: STRIP_SELECTORS }), [], decl);
  }
});

// The reviewer's mutants R3-C1 to R3-C7 and the variants of each kind of change the reviewer's list names. Every one is a rule that can reach the strip;
// each must be reported by the semantic net AND by the pin, on its own and appended to the real stylesheet.
const R3_MUTANTS = Object.freeze({
  'R3-C1': '.shell[DATA-MODE="geek"]>[role=region]{transform:rotateX(90deg)}',
  'R3-C2': '.shell[DATA-MODE=geek]>[aria-live]{font-size:.01px}',
  'R3-C3': 'div[aria-live]{color:rgba(0,0,0,0)}',
  'R3-C4': '[aria-live]{transform:scale(.001)}',
  'R3-C5': '.shell[DATA-MODE=geek]>[aria-live]{order:99}',
  'R3-C6': '.shell:has(> .region:last-child:not([hidden])) .alerts{margin-left:-200vw}',
  'R3-C7': '[aria-live]{filter:blur(40px)}',
});
const HIDING_DECLS = [
  // transform family
  'transform:rotateX(90deg)', 'transform:rotate(90deg)', 'transform:rotateY(90deg)', 'transform:scale(.001)', 'transform:scale3d(.01,.01,.01)', 'transform:scaleY(.001)', 'transform:skewX(89deg)',
  'transform:perspective(1px) rotateX(89deg)', 'transform:translateY(-100vh)', 'transform:translate(0,-9999px)', 'transform:matrix(1,0,0,.001,0,0)', 'transform:none', 'rotate:90deg', 'rotate:x 90deg',
  'scale:.001', 'scale:0', 'translate:0 -999px', 'translate:0 100vh', 'zoom:.01', 'zoom:0', 'transform-origin:0 0', 'perspective:1px',
  // paint family
  'filter:blur(40px)', 'filter:opacity(.01)', 'filter:brightness(0)', 'filter:contrast(0)', 'filter:invert(1)', 'filter:url(#x)', 'backdrop-filter:blur(99px)', 'opacity:.01', 'opacity:0', 'opacity:.5',
  'mix-blend-mode:difference', 'mix-blend-mode:multiply', 'isolation:isolate', 'will-change:transform',
  'clip-path:inset(100%)', 'clip-path:circle(0)', 'clip:rect(0,0,0,0)', 'mask:linear-gradient(transparent,transparent)', '-webkit-mask-image:linear-gradient(transparent,transparent)', 'mask-image:none', 'mask-size:0',
  // colour family
  'color:rgba(0,0,0,0)', 'color:transparent', 'color:#0000', 'color:#00000000', 'color:rgb(0 0 0 / 0)', 'color:rgba(0,0,0,.2)', 'color:hsl(0 0% 0% / 0)', 'color:var(--zz)', 'color:var(--ecco-nonexistent)',
  'background:rgba(0,0,0,0)', 'background-color:transparent', 'background:linear-gradient(red,red)', '-webkit-text-fill-color:transparent', 'text-shadow:0 0 9px red', 'border-left-color:rgba(0,0,0,0)',
  // size family
  'font-size:.01px', 'font-size:0', 'font-size:1px', 'font-size:var(--s)', 'font:1px/1 Arial', 'line-height:0', 'line-height:.001', 'line-height:0px', 'max-height:0', 'max-height:2px', 'height:0', 'height:1px',
  'height:100vh', 'width:0', 'max-width:0', 'min-height:5000px', 'min-width:100vw', 'block-size:0', 'inline-size:0', 'padding-top:9999px', 'padding:100vh', 'margin-top:9999px', 'margin:30px',
  // clipping and overflow
  'overflow:hidden', 'overflow:clip', 'overflow-y:hidden', 'overflow-x:clip', 'text-overflow:clip', 'white-space:nowrap', 'text-indent:-9999px', 'text-indent:9999px', 'letter-spacing:-1em', 'word-spacing:-9em',
  '-webkit-line-clamp:1', 'writing-mode:vertical-rl', 'direction:rtl',
  // visibility and display
  'visibility:hidden', 'visibility:collapse', 'content-visibility:hidden', 'content-visibility:auto', 'display:none', 'display:contents', 'display:none!important', 'display:block!important', 'contain:size', 'contain:strict',
  'contain:paint', 'contain:content', 'contain-intrinsic-size:0 0', 'pointer-events:none', 'user-select:none', 'appearance:none',
  // position and layering
  'position:absolute;left:-9999px', 'position:absolute;top:-9999px', 'position:fixed;top:-200vh', 'position:relative;left:-30px', 'position:sticky;top:-999px', 'inset:-9999px', 'inset-inline-start:-80vw',
  'margin-left:-200vw', 'margin-top:-999px', 'margin:-1000px', 'margin-inline-start:-50%', 'z-index:-1', 'position:relative;z-index:-1', 'order:99', 'order:-1', 'float:left', 'grid-row:99', 'grid-column:99',
  'grid-template-rows:0', 'grid-template-columns:0', 'align-self:end', 'place-self:end', 'animation:x 1s forwards', 'animation-name:x', 'transition:all 1s', 'content:"x"',
];

test('AC6 [r3] the reviewer mutants R3-C1 to R3-C7 are reported by the semantic net and by the pin, alone and appended to the real stylesheet (negative controls)', () => {
  for (const [id, css] of Object.entries(R3_MUTANTS)) {
    for (const text of [css, `${STYLE}\n${css}`]) {
      const n = nets(text);
      assert.notDeepEqual(n.semantic, [], `${id}: the semantic net missed it`);
      assert.notDeepEqual(n.pin, [], `${id}: the pin missed it`);
    }
  }
  // the reasons are the right ones, not an accident
  assert.match(violationText(R3_MUTANTS['R3-C1']), /mode-dependent selector/);
  assert.match(stripProblems(R3_MUTANTS['R3-C1'], { modeSelectors: MODE_SELECTORS, stripSelectors: STRIP_SELECTORS }).join('\n'), /not on the allowlist.*transform|names the alert strip/s);
  assert.match(stripProblems(R3_MUTANTS['R3-C2'], { modeSelectors: MODE_SELECTORS, stripSelectors: STRIP_SELECTORS }).join('\n'), /font-size/);
  assert.match(stripProblems(R3_MUTANTS['R3-C3'], { modeSelectors: MODE_SELECTORS, stripSelectors: STRIP_SELECTORS }).join('\n'), /color/);
  assert.match(stripProblems(R3_MUTANTS['R3-C4'], { modeSelectors: MODE_SELECTORS, stripSelectors: STRIP_SELECTORS }).join('\n'), /transform/);
  assert.match(stripProblems(R3_MUTANTS['R3-C5'], { modeSelectors: MODE_SELECTORS, stripSelectors: STRIP_SELECTORS }).join('\n'), /order/);
  assert.match(stripProblems(R3_MUTANTS['R3-C7'], { modeSelectors: MODE_SELECTORS, stripSelectors: STRIP_SELECTORS }).join('\n'), /filter/);
});

test('AC6 [r3] every hiding, shifting, clipping, shrinking, fading or re-ordering declaration, on every selector that can reach the strip, is reported by both nets (negative controls)', () => {
  const selectors = ['[aria-live]', '.alerts', '.alert', '.alert-head', '.shell', '.shell>*', 'div', '[role=region]', '.shell[DATA-MODE=geek] .alerts', '*', ':host', '.alert>.ico'];
  let n = 0;
  for (const decl of HIDING_DECLS) {
    for (const sel of selectors) {
      const css = `${sel}{${decl}}`;
      const semantic = strictAll(css);
      assert.notDeepEqual(semantic, [], `the semantic net accepted: ${css}`);
      assert.notDeepEqual(pinProblems(`${STYLE}\n${css}`, PIN), [], `the pin accepted: ${css}`);
      n += 1;
    }
    // appended to the real stylesheet the strict net still reports it (and does not report the real part)
    assert.notDeepEqual(strictAll(`${STYLE}\n[aria-live]{${decl}}`), [], `not caught when appended: ${decl}`);
  }
  assert.ok(n > 1000, `${n} combinations checked`);
});

test('AC6 [r3] a rule on a class the strip cannot carry is out of the semantic net by design, and the pin still refuses it (the same changes, off the strip)', () => {
  for (const decl of ['transform:rotateX(90deg)', 'font-size:.01px', 'filter:blur(40px)', 'color:rgba(0,0,0,0)', 'order:99', 'margin-left:-200vw']) {
    const css = `.row{${decl}}`;
    assert.notDeepEqual(pinProblems(`${STYLE}\n${css}`, PIN), [], css);
  }
  // and the decisions are not blanket refusals: ordinary additions that cannot touch the strip pass the semantic net (and need the pin updated to be allowed)
  for (const css of ['.row{margin-left:12px}', '.row{transform:rotate(1deg)}', '.tile{filter:none}', '.healthbar>span{min-width:5px}', '.alerts{gap:4px}', '.alert{padding:8px 10px;border-radius:10px}',
    '.alert-head{font-weight:600}', '.alert[data-severity="critical"]{border-left-color:#a00}', '.alert>.ico{width:24px;height:24px}', '.shell{--ecco-accent:#112233}', ':focus-visible{outline:3px solid #00f}',
    '@media (prefers-reduced-motion: reduce){*{animation:none!important}}']) {
    assert.deepEqual(strictAll(css), [], css);
    assert.notDeepEqual(pinProblems(`${STYLE}\n${css}`, PIN), [], `a new rule always needs a person: ${css}`);
  }
});

test('AC6 [r3] colours that are each allowed can still be unreadable together: only the pin and the Chrome check see that (documented limit, not a hole in the pin)', () => {
  const css = '.shell{--ecco-fg:#ffffff;--ecco-surface:#ffffff}';
  assert.deepEqual(strictAll(css), [], 'two visible colours are each acceptable to the semantic net');
  assert.notDeepEqual(pinProblems(`${STYLE}\n${css}`, PIN), [], 'but the pin refuses the new declarations');
  for (const bad of ['.shell{--ecco-fg:rgba(0,0,0,0)}', '.shell{--ecco-surface:transparent}', '.shell{--ecco-accent:rgba(1,2,3,.01)}', '.shell{--ecco-x:1}', '.shell{--zz:red}', '.shell{--ecco-fg:var(--zz)}',
    '.shell{--ecco-line:url(x)}', '.shell{--ecco-fg:hsl(0 0% 0% / 0)}']) {
    assert.notDeepEqual(strictAll(bad), [], bad);
  }
});

test('AC6 [r3] the strip element and its alert nodes are built by one literal each: no style, hidden, inert, class or other attribute can be added without changing a pinned line', () => {
  const once = (text) => assert.equal(code.split(text).length - 1, 1, text);
  once("mk(doc, 'div', { class: 'alerts', 'data-ecco-alert-strip': '', role: 'region', 'aria-label': 'Safety and status alerts', 'aria-live': 'polite' })");
  once("mk(doc, 'div', { class: 'alert', 'data-alert-id': a.id, 'data-severity': a.severity, 'data-alert-kind': a.kind, 'data-entity-id': a.entity_id || null, role: critical ? 'alert' : 'status' })");
  once("mk(doc, 'div', { class: 'alert quiet', 'data-alert-none': '' }, [icon(doc, 'live'), mk(doc, 'span', null, 'No active alerts.')])");
  once("strip.setAttribute('data-alert-count', String(alerts.length));");
  // nothing writes a style attribute or the hidden, inert or aria-hidden state of anything in the shell's tree except through the literals the other tests pin.
  // (Review round 4: this comment used to say aria-hidden writes were pinned here, but no assertion checked one. They are pinned by the AC6 [r4] tests below:
  // every setAttribute, toggleAttribute and removeAttribute site, the aria / role / tabindex keys of every literal, and the other doors to an accessibility property.)
  assert.doesNotMatch(code, /setAttribute\(\s*'(?:style|inert)'/);
  assert.doesNotMatch(code, /[{,]\s*(?:'style'|style|inert|'inert')\s*:/);
  assert.equal((code.match(/\.hidden\s*=/g) || []).length, 4, 'the four places that set hidden: the tiles, the empty note and the two bodies (the strip is none of them)');
  assert.doesNotMatch(code, /\bstrip\.(?:hidden|style|classList|className|inert)\b/);
  assert.doesNotMatch(code, /\.(?:alerts|strip)\b[^\n]*\.(?:hidden|style)\b/);
});

// ---------------------------------------------------------------------------------------------------------------------------
// Review round 4 (reviewer mutants J2 and J5): what a screen reader gets from the strip. The attribute writes are pinned (test/aria-guard.mjs).
// ---------------------------------------------------------------------------------------------------------------------------
const ANCHOR = "    ui.geekBody.hidden = mode !== 'geek';";
const plant = (snippet) => code.replace(ANCHOR, () => `${ANCHOR}\n    ${snippet}`);

test('AC6 [r4] every attribute the card writes, toggles or removes is written at a pinned site, and nothing else can reach an accessibility property', () => {
  assert.equal(code.split(ANCHOR).length - 1, 1, 'the anchor of the planted mutants is found once');
  assert.deepEqual(ariaProblems(code), []);
  // what the guard reads is what is there: 18 call sites (16 literal-named, the two builders that take the name from the literal object they are given)
  const calls = attributeCalls(withoutStyle(code));
  assert.equal(calls.length, ARIA_PIN.sites.length);
  assert.equal(calls.length, 18);
  assert.equal(calls.filter((c) => c.first === 'k').length, 2);
  assert.deepEqual(calls.filter((c) => /aria-|role|hidden|inert/i.test(c.first)).map((c) => `${c.method}(${c.first}) on ${c.receiver}`).sort(),
    ["setAttribute('aria-checked') on ui.opts[m]", "setAttribute('aria-hidden') on svg", "setAttribute('aria-pressed') on ui.problems"],
    'the only ARIA state written after the build is the radio option, the Problems-only toggle and the decorative icon: never the strip, the shell or an alert');
  // the strip's own attributes are written by its one literal (pinned above); aria-live is written in two literals only, the strip and the Geek status line
  assert.equal(stateKeys(withoutStyle(code))['aria-live'], 2);
  assert.equal(stateKeys(withoutStyle(code)).role, 10);
  assert.equal(Object.keys(stateKeys(withoutStyle(code))).filter((k) => /^(?:hidden|inert|style|slot|part|popover|contenteditable)$/.test(k)).length, 0, 'no hidden, inert or style key anywhere');
  // nothing in the source reaches the strip through a reflection property, a node API or an alias
  for (const [re, what] of FORBIDDEN) assert.doesNotMatch(withoutStyle(code), re, what);
});

test('AC6 [r4] the guard has teeth: the reviewer mutants J2 and J5 and every other way of hiding the strip from a screen reader, or muting it, are reported (negative controls)', () => {
  const planted = {
    'J2 aria-hidden on the strip in Geek Mode': "ui.strip.setAttribute('aria-hidden', mode === 'geek' ? 'true' : 'false');",
    'J5 aria-live off in Geek Mode': "ui.strip.setAttribute('aria-live', mode === 'geek' ? 'off' : 'polite');",
    'aria-live assertive in Geek Mode': "ui.strip.setAttribute('aria-live', mode === 'geek' ? 'assertive' : 'polite');",
    'aria-hidden on the shell, which holds the strip': "ui.shell.setAttribute('aria-hidden', mode === 'geek' ? 'true' : 'false');",
    'inert toggled on the strip': "ui.strip.toggleAttribute('inert', mode === 'geek');",
    'inert set on the shell': "ui.shell.setAttribute('inert', '');",
    'hidden toggled on the strip': "ui.strip.toggleAttribute('hidden', mode === 'geek');",
    'aria-live removed in Geek Mode': "if (mode === 'geek') ui.strip.removeAttribute('aria-live');",
    'role removed': "ui.strip.removeAttribute('role');",
    'role changed to presentation': "ui.strip.setAttribute('role', mode === 'geek' ? 'presentation' : 'region');",
    'role changed to none': "ui.strip.setAttribute('role', 'none');",
    'the label emptied': "ui.strip.setAttribute('aria-label', mode === 'geek' ? '' : 'Safety and status alerts');",
    'an upper-case attribute name': "ui.strip.setAttribute('ARIA-HIDDEN', 'true');",
    'a name in a template literal': 'ui.strip.setAttribute(`aria-hidden`, \'true\');',
    'a name built by concatenation': "ui.strip.setAttribute('aria-' + 'hidden', 'true');",
    'a name held in a variable': "const nm = 'aria-hidden'; ui.strip.setAttribute(nm, 'true');",
    'a double-quoted name': 'ui.strip.setAttribute("aria-hidden", "true");',
    'the strip found by a query': "this._root.querySelector('[data-ecco-alert-strip]').setAttribute('aria-hidden', 'true');",
    'ariaHidden by the reflection property': "ui.strip.ariaHidden = mode === 'geek' ? 'true' : 'false';",
    'ariaLive by the reflection property': "ui.strip.ariaLive = 'off';",
    'ariaLabel by the reflection property': "ui.strip.ariaLabel = '';",
    'role by the reflection property': "ui.strip.role = 'none';",
    'a reflection property by bracket': "ui.strip['ariaHidden'] = 'true';",
    'inert by property': 'ui.strip.inert = true;',
    'a class added to the strip': "ui.strip.classList.add('row');",
    'a class name assigned': "ui.strip.className = 'row';",
    'an attribute node': "ui.strip.setAttributeNode(this.ownerDocument.createAttribute('aria-hidden'));",
    'a namespaced attribute': "ui.strip.setAttributeNS(null, 'aria-hidden', 'true');",
    'a named item': "ui.strip.attributes.setNamedItem(x);",
    'Object.assign onto the strip': "Object.assign(ui.strip, { ariaHidden: 'true' });",
    'an alias of setAttribute': "const sa = ui.strip.setAttribute; sa.call(ui.strip, 'aria-hidden', 'true');",
    'setAttribute reached by bracket': "ui.strip['setAttribute']('aria-hidden', 'true');",
    'setAttribute bound': "ui.strip.setAttribute.bind(ui.strip)('aria-hidden', 'true');",
    'an extra literal key in a built element': "mk(this.ownerDocument, 'div', { 'aria-hidden': 'true' });",
    'an extra role key': "mk(this.ownerDocument, 'div', { role: 'presentation' });",
    'a style key': "mk(this.ownerDocument, 'div', { style: 'display:none' });",
    'a hidden key': "mk(this.ownerDocument, 'div', { hidden: true });",
    'a second aria-hidden write on an icon (the pinned site twice)': "const svg = this.ownerDocument.createElement('i'); svg.setAttribute('aria-hidden', 'true');",
    'an unrelated new attribute write (every new site is a decision)': "ui.summary.setAttribute('data-zz', 'x');",
  };
  const names = Object.keys(planted);
  assert.ok(names.length >= 35, `${names.length} planted breaks`);
  for (const [what, snippet] of Object.entries(planted)) {
    assert.notDeepEqual(ariaProblems(plant(snippet)), [], `not reported: ${what}`);
  }
  // the report says why, in words a person can act on
  assert.match(ariaProblems(plant(planted['J2 aria-hidden on the strip in Geek Mode'])).join('\n'), /attribute write not pinned[^:]*: setAttribute\('aria-hidden'\) on ui\.strip/);
  assert.match(ariaProblems(plant(planted['J5 aria-live off in Geek Mode'])).join('\n'), /attribute write not pinned[^:]*: setAttribute\('aria-live'\) on ui\.strip/);
  assert.match(ariaProblems(plant(planted['a name in a template literal'])).join('\n'), /not a plain single-quoted literal/);
  assert.match(ariaProblems(plant(planted['ariaHidden by the reflection property'])).join('\n'), /ARIA reflection property/);
  assert.match(ariaProblems(plant(planted['an extra literal key in a built element'])).join('\n'), /the key 'aria-hidden' is written 3 time\(s\)/);
  // each planted break is also reported when it is appended at the end of the module rather than inside _applyMode, so the guard does not depend on the anchor
  for (const [what, snippet] of Object.entries(planted)) assert.notDeepEqual(ariaProblems(`${code}\n${snippet}\n`), [], `not reported at the end of the module: ${what}`);
});

test('AC6 [r4] the guard also refuses a changed or removed pinned write, and ignores formatting', () => {
  const real = ["svg.setAttribute('aria-hidden', 'true');", "ui.problems.setAttribute('aria-pressed', this.filters.problems ? 'true' : 'false');",
    "ui.opts[m].setAttribute('aria-checked', m === mode ? 'true' : 'false');", "ui.shell.setAttribute('data-theme', hass.themes.darkMode ? 'dark' : 'light');"];
  for (const text of real) assert.equal(code.split(text).length - 1, 1, `the pinned write is found once: ${text}`);
  // the receiver changes (the decorative icon's aria-hidden is written on the strip instead), or the attribute name changes, or the write is gone
  assert.notDeepEqual(ariaProblems(code.replace(real[0], () => "ui.strip.setAttribute('aria-hidden', 'true');")), []);
  assert.notDeepEqual(ariaProblems(code.replace(real[0], () => "svg.setAttribute('aria-live', 'true');")), []);
  assert.notDeepEqual(ariaProblems(code.replace(real[0], () => '')), []);
  assert.notDeepEqual(ariaProblems(code.replace(real[1], () => "ui.strip.setAttribute('aria-pressed', 'true');")), []);
  assert.notDeepEqual(ariaProblems(code.replace(real[2], () => "ui.shell.setAttribute('aria-checked', 'true');")), []);
  // formatting and the argument's own text are free: only the method, the name and the receiver are pinned
  assert.deepEqual(ariaProblems(code.replace(real[1], () => "ui.problems\n      .setAttribute(\n        'aria-pressed' ,\n        this.filters.problems ? 'false' : 'true' );")), []);
  assert.deepEqual(ariaProblems(code.replace(real[2], () => "ui.opts[m].setAttribute( 'aria-checked', 'true' );")), []);
  // the guard reads code with its comments stripped (as every test in this file does), so a sentence in a comment is never a write; it does not strip them itself
  assert.notDeepEqual(ariaProblems(`${code}\n// ui.strip.setAttribute('aria-hidden', 'true')`), [], 'handed a comment as code the guard reports it: strip comments first');
  assert.equal(code.includes("ui.strip.setAttribute('aria-hidden'"), false, 'the comment-stripped source holds no such write');
  // the stylesheet is not source: its attribute selectors ([aria-checked="true"], [aria-expanded="false"]) are no write, and the guard reads the card without it
  assert.ok(code.includes('[aria-checked="true"]') && !withoutStyle(code).includes('[aria-checked="true"]'));
  assert.deepEqual(ariaProblems(code), []);
});

// ---------------------------------------------------------------------------------------------------------------------------
// Review round 5 ([r5]). Four reviewer mutants (J13, J21: a custom property set on the shell by the call that sets one on a bar segment or a ring; AR08: a shadow root
// on the strip) were caught only by the opt-in browser check, so on a machine with no Chrome they passed every suite. The first two slipped through because the round-1
// pin read the SHAPE of an inline-style call ('--ecco-<letters>', then String(...)) and not its receiver or its name.
// ---------------------------------------------------------------------------------------------------------------------------
test('inline style [r5]: the two setProperty calls are exactly the bar segment width and the tile ring percentage; receiver, property name and value are pinned (reviewer mutants J13, J21)', () => {
  const total = (code.match(/\.style\.setProperty\(/g) || []).length;
  const sites = [...code.matchAll(/([A-Za-z_][\w$.]*(?:\[[^\]]*\])*)\.style\.setProperty\(\s*'(--[a-z-]+)'\s*,\s*([^;]*?)\);/g)].map((m) => [m[1], m[2], m[3]]);
  assert.equal(total, 2);
  assert.equal(sites.length, total, 'every call has a quoted name and a receiver the pin can read');
  assert.deepEqual(sites, [['seg', '--ecco-w', 'String(c[s])'], ['ringEl', '--ecco-p', 'String(ring.pct)']], 'receiver, name and value of both calls');
  // the two receivers are made once, each as a plain span of its own, and never assigned again (so neither can be pointed at the shell, the host or the strip)
  assert.equal((code.match(/\bconst seg = mk\(doc, 'span', \{ 'data-seg': s, title: /g) || []).length, 1);
  assert.equal((code.match(/\bconst ringEl = mk\(doc, 'span', \{ class: 'ring', 'aria-hidden': 'true' \}/g) || []).length, 1);
  assert.equal((code.match(/(?<![\w$.-])(?:seg|ringEl)\s*=(?!=)/g) || []).length, 2, 'only the two declarations assign them');
  assert.doesNotMatch(code, /\b(?:seg|ringEl)\.(?:parentNode|parentElement|closest|getRootNode|ownerDocument)\b/, 'neither receiver is walked up to an ancestor');
  // the two custom properties that are set are read by the stylesheet for exactly these two elements (the bar segments and the rings), and by nothing else
  assert.match(src, /\.healthbar>span\{flex:var\(--ecco-w,1\) 1 0;/);
  assert.match(src, /\.ring\{[^}]*calc\(var\(--ecco-p,0\)\*1%\)/);
  assert.equal((src.match(/var\(--ecco-w\b/g) || []).length, 1, '--ecco-w is read once');
  assert.equal((src.match(/var\(--ecco-p\b/g) || []).length, 1, '--ecco-p is read once');
});

test('shadow roots [r5]: attachShadow is written once, as this.attachShadow in the constructor of the card; no other element is given a shadow root (reviewer mutant AR08)', () => {
  const lines = code.split('\n').filter((l) => /attachShadow|shadowRoot|attachInternals|ShadowRoot/.test(l));
  assert.equal(lines.length, 1, `lines that mention a shadow root: ${JSON.stringify(lines)}`);
  assert.equal(lines[0], "    this._root = typeof this.attachShadow === 'function' ? this.attachShadow({ mode: 'open' }) : null;");
  assert.equal((code.match(/attachShadow/g) || []).length, 2, 'the test and the call, on that one line');
  const cls = code.indexOf('class EccoModeShell');
  const ctor = code.indexOf('  constructor() {', cls);
  const next = code.indexOf('\n  static getStubConfig()', ctor);
  const at = code.indexOf(lines[0]);
  assert.ok(cls > 0 && ctor > cls && next > ctor, 'the constructor of the card element is found');
  assert.ok(at > ctor && at < next, 'and the call is inside it');
  // nothing reads a shadow root back from another element, and nothing is attached to a variable that is not `this`
  assert.doesNotMatch(code, /\b(?!this\b)\w+\.attachShadow\b/);
  assert.doesNotMatch(code, /\[\s*['"`]attach/);
});

// ---------------------------------------------------------------------------------------------------------------------------
// Review round 6 ([r6]). Reviewer mutant P07 wrote `this.o.container.parentNode.style['setProperty']('--ecco-fg', 'transparent')` next to the pinned bar-segment call. The round-5 pin counted `.style.setProperty(`
// (two, so unchanged), read only the two literal sites, and scanned `.style.name` (the bracket form is not one), so every node suite passed; only the browser check failed it. The class is "something writes the
// inline style of an element other than at the two pinned sites", so this pins the STRUCTURE, not a spelling: the word `style` is a property of exactly two calls (the only other uses are the card's one <style> element and its stylesheet text), and no other way of writing a style exists.
// ---------------------------------------------------------------------------------------------------------------------------
const plainCode = withoutStyle(code);
// the three statements that build the card's one <style> element from its stylesheet text are the only other place the word appears
const STYLE_BUILDER = ["const style = mk(doc, 'style');", 'style.textContent = STYLE;', 'this._root.replaceChildren(style, shell);'];
const styleWordsLeft = (text) => {
  let rest = text;
  for (const b of STYLE_BUILDER) rest = rest.replace(b, '');
  rest = rest.replace(/\b(?:seg|ringEl)\.style\.setProperty\(/g, '');
  return [...rest.matchAll(/\bstyle\b/gi)].map((m) => rest.slice(Math.max(0, m.index - 12), m.index + 20).replace(/\s+/g, ' '));
};
const styleProblems = (text) => {
  const bad = [];
  const left = styleWordsLeft(text);
  if (left.length) bad.push(`the word style is used outside the two pinned calls and the stylesheet builder: ${JSON.stringify(left)}`);
  if ((text.match(/\.style\.setProperty\(/g) || []).length !== 2) bad.push('not two direct setProperty calls');
  if ((text.match(/\bsetProperty\b/g) || []).length !== 2) bad.push('setProperty is not written twice');
  if (/\.style\s*\??\.?\s*\[/.test(text) || /\[\s*(['"`])[^'"`\]]*style[^'"`\]]*\1\s*\]/i.test(text)) bad.push('computed access on a style');
  if (/\[\s*(['"`])[^'"`\]]*(?:setProperty|cssText|Property)[^'"`\]]*\1\s*\]/.test(text)) bad.push('a style method reached by bracket');
  if (/\bcssText\b/.test(text)) bad.push('cssText');
  if (/['"`]\s*(?:sty|styl|st|s)['"`]\s*\+|\+\s*['"`]\s*(?:le|yle|tyle)['"`]|['"`]set['"`]\s*\+|\+\s*['"`]Property['"`]/.test(text) || /\$\{\s*['"`](?:le|Property|yle)['"`]\s*\}/.test(text)) bad.push('a name built from pieces');
  return bad;
};

test('inline style [r6]: the word style appears in the code (outside the stylesheet text) only as the receiver of the two pinned setProperty calls; no computed member access, alias, destructuring, key, string or built name reaches a style (reviewer mutant P07)', () => {
  for (const b of STYLE_BUILDER) assert.equal(plainCode.split(b).length - 1, 1, `the builder statement is written once: ${b}`);
  assert.equal([...plainCode.matchAll(/\bstyle\b/gi)].length, 7, 'two pinned calls and the five words of the three builder statements');
  assert.deepEqual(styleWordsLeft(plainCode), []);
  assert.deepEqual(styleProblems(plainCode), []);
  assert.equal((plainCode.match(/\bremoveProperty\b|\bgetPropertyValue\b|\bgetPropertyPriority\b|\bsetPropertyValue\b/g) || []).length, 0);
  assert.doesNotMatch(plainCode, /\bfromCharCode\b|\batob\b|\bbtoa\b|\bdecodeURIComponent\b|\bunescape\b|\bString\s*\.\s*raw\b/, 'no way of spelling a name from pieces');
  // every other door to a style or a stylesheet: cssText, Object.assign onto a style, the CSSOM, adoptedStyleSheets, a stylesheet or a style element made from code, the dataset and class reflections
  for (const re of [/\bcssText\b/, /\battributeStyleMap\b/, /\badoptedStyleSheets\b/, /\binsertRule\b/, /\bdeleteRule\b/, /\breplaceSync\b/, /\bCSSStyleSheet\b/, /\bstyleSheets\b/, /\bgetComputedStyle\b/,
    /\bcssRules\b/, /\bsetAttribute\(\s*['"`]style['"`]/, /\bcreateElement\(\s*['"`]style['"`]/, /\bcreateElementNS\([^)]*['"`]style['"`]/, /\bsheet\b/, /\bCSS\s*\./,
    /\.dataset\b/, /\bclassList\b/, /\bclassName\b/]) assert.doesNotMatch(plainCode, re, String(re));
});

test('inline style [r6]: the receiver of each pinned call is a bare local variable (seg, ringEl): nothing is walked up to an ancestor of the strip, a shell or the host first', () => {
  const receivers = [...plainCode.matchAll(/([A-Za-z_$][\w$.]*(?:\[[^\]]*\])*(?:\([^)]*\))*)\.style\.setProperty\(/g)].map((m) => m[1]);
  assert.deepEqual(receivers, ['seg', 'ringEl']);
  for (const r of receivers) assert.match(r, /^[A-Za-z_$][\w$]*$/, `receiver ${r}`);
  // and the two locals are made once, each by the builder, and never assigned again (the round-5 pin; this closes on it)
  assert.equal((plainCode.match(/\bconst seg = mk\(/g) || []).length, 1);
  assert.equal((plainCode.match(/\bconst ringEl = mk\(/g) || []).length, 1);
  assert.equal((plainCode.match(/(?<![\w$.-])(?:seg|ringEl)\s*=(?!=)/g) || []).length, 2);
});

test('inline style [r6]: the planted forms are each refused by the structure (negative controls: bracket call, alias, computed key, cssText, Object.assign, a property, a third call, a built name)', () => {
  const anchor = "      seg.style.setProperty('--ecco-w', String(c[s]));";
  assert.equal(plainCode.split(anchor).length - 1, 1, 'the anchor of the planted forms is found once');
  const forms = [
    "      this.o.container.parentNode.style['setProperty']('--ecco-fg', 'transparent');",
    "      const st = this.o.container.parentNode.style; st.setProperty('--ecco-fg', 'transparent');",
    "      this.o.container.parentNode['style'].setProperty('--ecco-fg', 'transparent');",
    "      this.o.container.parentNode.style.cssText = '--ecco-fg:transparent';",
    "      Object.assign(this.o.container.parentNode.style, { color: 'transparent' });",
    "      this.o.container.parentNode.style.color = 'transparent';",
    "      this.o.container.parentNode.style.setProperty('--ecco-fg', 'transparent');",
    "      const { style } = this.o.container.parentNode; void style;",
    "      this.o.container.parentNode[`sty${'le'}`].color = 'transparent';",
    "      this.o.container.parentNode.style[`set${'Property'}`]('--ecco-fg', 'transparent');",
    "      this.o.container.parentNode[['sty', 'le'].join('')].color = 'transparent';",
  ];
  assert.deepEqual(styleProblems(plainCode), [], 'the real source is clean by these same rules');
  for (const f of forms) {
    const planted = plainCode.replace(anchor, () => `${anchor}\n${f}`);
    const bad = styleProblems(planted);
    // the last form spells the word only in pieces: the structural rule is that no string ends in 'sty' and no join builds a name; that one is refused by the static source rules below
    if (f.includes(".join('')")) assert.ok(bad.length > 0 || /\bjoin\(\s*['"`]{2}\s*\)/.test(planted), f);
    else assert.notDeepEqual(bad, [], f);
  }
});

// Review round 6 ([r6]), reviewer mutant K02 and the finding NIT-1: a catalogue is data, and a pattern in it was code. The rule is now that no expression is ever built from catalogue data at all.
test('catalogue key patterns [r6]: no regular expression is built from data (the one RegExp constructor is the fixed list of read-only domains); the fragment rule is one literal, and its numbers agree with the exported limits', async () => {
  const mod = await import(cardUrl);
  assert.equal((code.match(/\bRegExp\b/g) || []).length, 1, 'RegExp is named once in the code: no alias, no second constructor, no .test on a built expression');
  const line = code.split('\n').find((l) => /\bRegExp\b/.test(l));
  assert.match(line, /^const MORE_INFO_ID = new RegExp\(`\^\(\?:\$\{MORE_INFO_DOMAINS\.join\('\|'\)\}\)/, 'and it is the one built from the constant list of domains');
  assert.equal((code.match(/const EXTRA_FRAGMENT = \/\^\[a-z0-9_\]\{1,80\}\$\/;/g) || []).length, 1, 'the fragment rule is one literal');
  assert.equal(mod.EXTRA_FRAGMENT_MAX, 80);
  assert.equal(mod.EXTRA_FRAGMENTS_MAX, 40);
  assert.match(code, /const EXTRA_KEY_CAP = 200;/);
  assert.match(code, /const step = EXTRA_KEY_CAP - \(EXTRA_FRAGMENT_MAX - 1\);/, 'the windows overlap by one less than the longest fragment');
  assert.equal(mod.LIMITS.scanBound, 20000);
  assert.equal(mod.LIMITS.stringCap, 4000);
  // the one place a string is read for secrets cuts nothing before it reads: the read comes first, the cut after, and a text over the bound is withheld without being read
  const fn = code.slice(code.indexOf('function redactString('), code.indexOf('function redactNode('));
  const order = ['if (s.length > LIMITS.scanBound) return WITHHELD;', 'if (valueReason(t, digestOk, digestKey) !== null) return WITHHELD;', 'const cut = t.length > LIMITS.stringCap'].map((x) => fn.indexOf(x));
  assert.ok(order.every((i) => i > 0) && order[0] < order[1] && order[1] < order[2], `bound, then read, then cut: ${order}`);
  assert.equal((fn.match(/\.slice\(/g) || []).length, 1, 'redactString slices once, for the display, after the read');
  assert.ok(fn.indexOf('.slice(') > order[1], 'and that slice is after the read');
});

// ---------------------------------------------------------------------------------------------------------------------------
// Review round 7 ([r7]). Three static nets, each closing a class and not an instance.
//  (1) THE REDACTION PATH CUTS NOTHING. Reviewer mutants N31, N32 and N33 added a chunked read INSIDE valueReason, where the round-6 pin (which froze the one line of redactString) did not look. The class is "a
//      function on the redaction path reads part of a string": so every function on it is read here, and the only calls that cut or split text, and the only loop that steps by more than one, are the
//      documented ones, by function and by count.
//  (2) EVERY QUANTIFIER OF EVERY RULE IS ACCOUNTED FOR. A rule is linear when no unbounded quantifier can be walked again from many starts; the number of unbounded quantifiers of each rule is pinned, so
//      a bound taken off (or a rule written back as it was in round 6) changes a count and fails here as well as in perf.test.mjs.
//  (3) NO ANIMATION AND NO DYNAMIC STYLESHEET API. Reviewer mutant N21 hid the alert strip in Geek Mode with the Web Animations API (`strip.animate(...)`, fill forwards); the static rules refused every other way
//      of hiding it but not this one, so only the headless browser check failed it. The Web Animations API and every dynamic stylesheet API are now refused, with planted forms as negative controls.
// ---------------------------------------------------------------------------------------------------------------------------
const topLevel = (name) => {
  const m = new RegExp(`^(?:export )?(?:function ${name}\\(|const ${name} = )`, 'm').exec(code);
  assert.ok(m, `the declaration of ${name} is found`);
  const rest = code.slice(m.index + 1);
  const next = rest.search(/\n(?:export |function |const |let |class )/);
  return code.slice(m.index, next < 0 ? undefined : m.index + 1 + next);
};
const REDACTION_PATH = ['cleanText', 'fold', 'keyTokens', 'compileExtra', 'keyHasFragment', 'isSecretKey', 'valueReason', 'newScan', 'redactString', 'keyInfo', 'redactNode', 'newCtx', 'redactValue', 'redactAttributes'];
const CUTTERS = /\.(slice|substring|substr|split|splice|matchAll|subarray|at)\(/g;
// what each function may cut, and why: the display cut (cleanText, redactString: after the read), the tokeniser (the whole key, in words), the fragment list's length, the one documented window of a key (the fragment
// search: overlapping by one less than the longest fragment) and the first 200 characters of a key NAME (the name is shown cut at 120)
const ALLOWED_CUTS = { cleanText: { slice: 1 }, keyTokens: { split: 1 }, compileExtra: { slice: 1 }, keyHasFragment: { slice: 1 }, redactString: { slice: 1 }, redactNode: { slice: 1 } };
const cutsIn = (text) => {
  const out = {};
  for (const m of text.matchAll(CUTTERS)) out[m[1]] = (out[m[1]] || 0) + 1;
  return out;
};

test('redaction path [r7]: every function on it is read; the only calls that cut or split text are the documented ones (the display cut after the read, the key tokeniser, the fragment count, the one overlapping key window, the 200-character key-name scan); none is in valueReason (reviewer mutants N30 to N33)', () => {
  for (const name of REDACTION_PATH) assert.deepEqual(cutsIn(topLevel(name)), ALLOWED_CUTS[name] || {}, `${name}: the calls that cut text`);
  const vr = topLevel('valueReason');
  assert.equal((vr.match(/\.match\(/g) || []).length, 1, 'valueReason has one match, and it is of the whole text');
  assert.match(vr, /for \(const t of s\.match\(RE_B64\) \|\| \[\]\)/);
  assert.doesNotMatch(vr, /(?<!const\s)\braw\s*=(?!=)/, 'the text that is read is never reassigned');
  assert.doesNotMatch(vr, /(?<!const\s)\bs\s*=(?!=)/);
  // no loop on the path steps by more than one, except the key window; none carries an index into a string
  for (const name of REDACTION_PATH) {
    const steps = [...topLevel(name).matchAll(/for\s*\([^)]*;\s*[A-Za-z_]+\s*\+=(?!\s*1\s*\))[^)]*\)/g)].map((m) => m[0].replace(/\s+/g, ' '));
    assert.deepEqual(steps, name === 'keyHasFragment' ? ['for (let i = 0; i < lower.length; i += step)'] : [], `${name}: loops that step by more than one`);
  }
  for (const re of [/\blastIndex\b/, /\.exec\(/, /\.sticky\b/, /\bsetTimeout\b/, /\bsubarray\b/]) for (const name of REDACTION_PATH) assert.doesNotMatch(topLevel(name), re, `${name}: ${re}`);
  // the key window overlaps by one less than the longest fragment (the existing round-6 pin), and the three numbers stay what they were
  assert.match(topLevel('keyHasFragment'), /const step = EXTRA_KEY_CAP - \(EXTRA_FRAGMENT_MAX - 1\);/);
  assert.match(topLevel('redactNode'), /valueReason\(k\.length > 200 \? k\.slice\(0, 200\) : k, false\)/);
});

test('redaction path [r7]: planted cuts in each function of the path are each refused (negative controls: a chunk, a prefix, a substring, a split, a window in valueReason, redactString, redactNode, isSecretKey and keyInfo)', () => {
  const planted = [
    ['valueReason', 'function valueReason(raw, digestOk, digestKey = false) {\n  if (raw.length < 6) return null;', '  if (raw.length > 3000) { for (let i = 0; i < raw.length; i += 2800) { const r = valueReason(raw.substring(i, i + 3000), digestOk, digestKey); if (r !== null) return r; } return null; }'],
    ['valueReason', 'function valueReason(raw, digestOk, digestKey = false) {\n  if (raw.length < 6) return null;', '  if (raw.length > 1024) raw = raw.slice(0, 1024);'],
    ['valueReason', 'function valueReason(raw, digestOk, digestKey = false) {\n  if (raw.length < 6) return null;', "  if (raw.split('\\n').length > 9) return null;"],
    ['isSecretKey', 'function isSecretKey(key, extra) {', '  key = String(key).substr(0, 100);'],
    ['keyInfo', 'function keyInfo(key, ctx) {', '  key = key.slice(0, 50);'],
    ['redactString', 'function redactString(s, key, scan, digest) {', '  s = s.slice(0, 8000);'],
    ['redactNode', 'function redactNode(v, key, ctx, depth) {', "  if (typeof v === 'string') v = v.substring(0, 5000);"],
    ['keyTokens', 'function keyTokens(key) {', '  key = String(key).slice(0, 300);'],
  ];
  for (const [name, anchor, extra] of planted) {
    assert.equal(code.split(anchor).length - 1, 1, `the anchor of ${name} is found once`);
    const text = code.replace(anchor, () => `${anchor}\n${extra}`);
    const m = new RegExp(`^(?:export )?function ${name}\\(`, 'm').exec(text);
    const rest = text.slice(m.index + 1);
    const body = text.slice(m.index, m.index + 1 + rest.search(/\n(?:export |function |const |let |class )/));
    const got = cutsIn(body);
    assert.notDeepEqual(got, ALLOWED_CUTS[name] || {}, `${name}: the planted cut is seen (${extra.slice(0, 50)})`);
  }
});

// the number of UNBOUNDED quantifiers (a star, a plus, or {n,}) of each rule, outside character classes and escapes. Each is linear by construction: the text after an at sign or a dotted suffix is read once from
// the one start; a tail after the match is complete; a run that no other start can enter (a run of characters that the start itself is not); a bounded count of starts times a bounded run.
// Review round 8: six of these numbers CHANGED, on purpose and in the direction the owner asked for. Round 7 bounded some quantifiers ({0,64}, {1,256}, {4,512}, {1,64}, {1,253}, {0,13}) and so lost matches; the six
// rules are now written with NO bound on any component and still read each run once (a look-behind from the second dot, one start per separator with two look-aheads, a look-behind from the semicolon, a look-behind from
// /services/, the last letter of a run, and the round-6 key block, which is linear as it stands). jwt 1 -> 2, key block 0 -> 1, url token 1 -> 2, connection pairs 7 -> 4, MAC address (dotted) 0 -> 2, webhook path 2 -> 3.
// The proof that they lose nothing is test/differential.test.mjs; the proof that they are linear is test/perf.test.mjs (every rule alone, on every near-miss text).
const UNBOUNDED = {
  'jwt': 2, 'key block': 1, 'url credentials': 1, 'connection string': 1, 'url token': 2, 'credential pair': 3, 'connection pairs': 4, 'pass pair': 7, 'wifi credentials': 0, 'bearer': 2,
  'known token': 5, 'email address': 4, 'IPv4 address': 0, 'IPv6 address': 0, 'MAC address': 0, 'MAC address (dotted)': 2, 'MAC address (spaced)': 0, 'coordinates': 4, 'labelled coordinate': 2,
  'hemisphere coordinates': 5, 'webhook path': 3, 'internal host name': 1, 'private host name': 0,
};
const unboundedQuantifiers = (src) => {
  const out = [];
  let inClass = false;
  for (let i = 0; i < src.length; i += 1) {
    const c = src[i];
    if (c === '\\') {
      i += 1;
      continue;
    }
    if (inClass) {
      if (c === ']') inClass = false;
      continue;
    }
    if (c === '[') inClass = true;
    else if (c === '*' || c === '+') out.push(src.slice(Math.max(0, i - 12), i + 1));
    else if (c === '{') {
      const m = /^\{(\d+),(\d*)\}/.exec(src.slice(i));
      if (m) {
        if (m[2] === '') out.push(src.slice(Math.max(0, i - 12), i + m[0].length));
        i += m[0].length - 1;
      }
    }
  }
  return out;
};

test('rules [r7]: the number of unbounded quantifiers of every rule is pinned (23 rules); a bound taken off, or a rule written back as it was in round 6, changes a count (reviewer finding: the dotted MAC look-ahead, the e-mail, the host name)', async () => {
  const { SCAN_RULES } = await import(cardUrl);
  assert.equal(SCAN_RULES.length, 23);
  assert.deepEqual(SCAN_RULES.map((r) => r.reason).sort(), Object.keys(UNBOUNDED).sort());
  for (const r of SCAN_RULES) assert.equal(unboundedQuantifiers(r.pattern.source).length, UNBOUNDED[r.reason], `${r.reason}: ${JSON.stringify(unboundedQuantifiers(r.pattern.source))}`);
  // the counter itself: it sees a star, a plus and {n,}, and not a bounded count, an escaped one or one inside a class
  assert.deepEqual(unboundedQuantifiers('a*b+c{2,}d{2,5}e\\*f\\+[x*+]g{3}').length, 3);
  // the round-6 patterns, which are the ones the reviewer's probe made walk, have more of them than the rules that replaced them
  const r6 = { 'MAC address (dotted)': /\b(?=[0-9a-f.]*[a-f])[0-9a-f]{4}\.[0-9a-f]{4}\.[0-9a-f]{4}\b/i, 'email address': /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b/,
    'private host name': /\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:local|lan|internal|home\.arpa|localdomain)\b/i, 'url credentials': /\b[a-z][a-z0-9+.-]*:\/\/[^\s/?#@]*@/i };
  for (const [reason, re] of Object.entries(r6)) assert.notEqual(unboundedQuantifiers(re.source).length, UNBOUNDED[reason], `${reason}: the round-6 form is not the pinned one`);
});

test('rules [r7]: the pre-tests are wired as they were (three entries, asked for every rule, in step with the table), so a pre-test that is dropped, loosened, never asked or asked of the next rule is a change of the code that is seen here too', () => {
  const table = code.slice(code.indexOf('const RULE_PRETESTS = {'), code.indexOf('const PRETEST = RULES.map'));
  assert.equal(table.replace(/\s+/g, ' ').trim(), 'const RULE_PRETESTS = { \'pass pair\': /(?:pass|pw)(?:\\s*["\']|=)/i, \'MAC address (dotted)\': /[0-9a-f]{4}\\.[0-9a-f]{4}\\.[0-9a-f]{4}/i, \'private host name\': /\\.(?:local|lan|internal|home\\.arpa|localdomain)\\b/i, };');
  const vr = topLevel('valueReason');
  assert.equal((vr.match(/PRETEST\[i\] !== undefined && !PRETEST\[i\]\.test\(s\)\) continue;/g) || []).length, 1);
  assert.equal((vr.match(/if \(gate !== null && !s\.includes\(gate\)\) continue;/g) || []).length, 1);
  assert.equal((vr.match(/if \(re\.test\(s\)\) return reason;/g) || []).length, 1);
  assert.match(vr, /const \[reason, gate, re\] = RULES\[i\];/);
  assert.match(code, /const PRETEST = RULES\.map\(\(\[reason\]\) => RULE_PRETESTS\[reason\]\);/);
});

test('scan budget [r7]: the budget is charged where a string is read and where a key is read, withholds when it is gone, and an export gives each row its own (the wiring, by the source)', () => {
  assert.match(code, /entityChars: 100000,/);
  assert.match(topLevel('newScan'), /\{ left: LIMITS\.entityChars \}/);
  const rs = topLevel('redactString');
  assert.ok(rs.indexOf('scan.left -= t.length;') > rs.indexOf('const t = s;') && rs.indexOf('scan.left -= t.length;') < rs.indexOf('valueReason(t, digestOk, digestKey)'), 'the charge is after the bound and before the read');
  assert.match(rs, /if \(scan\.left < 0\) return WITHHELD;/);
  const ki = topLevel('keyInfo');
  assert.match(ki, /ctx\.scan\.left -= Math\.min\(String\(key\)\.length, LIMITS\.scanBound\);/);
  assert.match(ki, /if \(ctx\.scan\.left < 0\) return KEY_UNREAD;/);
  assert.ok(ki.indexOf('return KEY_UNREAD') < ki.indexOf('isSecretKey(key, ctx.extra)'), 'a key the budget cannot pay for is not read');
  assert.ok(ki.indexOf('ctx.keys.set(key, info)') > ki.indexOf('return KEY_UNREAD'), 'and what it says is not remembered');
  const rn = topLevel('redactNode');
  assert.match(rn, /if \(ctx\.scan\.left <= 0\) \{/);
  assert.match(rn, /if \(ctx\.eachItem && depth === 0\) ctx\.scan\.left = LIMITS\.entityChars;/);
  assert.match(code, /redactValue\(\(Array\.isArray\(rows\) \? rows : \[\]\)\.map\(exportRow\), \{ eachItem: true \}\)/);
  // review round 8: the options of the entity carry the count of values visited too (the snapshot charges them), and the attributes are the LAST thing read (the state, the name and the unit are charged first)
  assert.match(code, /const opts = \{ extraKeyPatterns: cat\.extraPatterns, scan: newScan\(\), work \};/);
  const pf = topLevel('partsFor');
  assert.ok(pf.indexOf('redactValue(stateStr, opts)') > 0 && pf.indexOf('redactValue(stateStr, opts)') < pf.indexOf('redactValue(attrsRaw.friendly_name') && pf.indexOf('redactValue(attrsRaw.friendly_name') < pf.indexOf('redactValue(attrsRaw.unit_of_measurement')
    && pf.indexOf('redactValue(attrsRaw.unit_of_measurement') < pf.indexOf('redactAttributes(attrsRaw, opts)'), 'the order of charging: the state, the name, the unit, then every attribute');
  assert.equal((code.match(/\bnewScan\(\)/g) || []).length, 2, 'a budget is made in partsFor and as the default of a call: nowhere else');
});

// ---- (3) the Web Animations API and every dynamic stylesheet API
const ANIMATION_APIS = [/\.animate\s*\(/, /\bgetAnimations\b/, /\bKeyframeEffect\b/, /\bAnimationEffect\b/, /\bnew\s+Animation\b/, /\bAnimationTimeline\b/, /\bDocumentTimeline\b/, /\bScrollTimeline\b/, /\bViewTimeline\b/,
  /\bcomputedStyleMap\b/, /\bcommitStyles\b/, /\bAnimation\s*\(/, /\.timeline\b/, /\bpersist\s*\(\s*\)/, /\bfinish\s*\(\s*\)/, /\bonfinish\b/];
const STYLESHEET_APIS = [/\badoptedStyleSheets\b/, /\bCSSStyleSheet\b/, /\bCSSStyleDeclaration\b/, /\binsertRule\b/, /\bdeleteRule\b/, /\baddRule\b/, /\bremoveRule\b/, /\breplaceSync\b/, /\bregisterProperty\b/, /\bpaintWorklet\b/,
  /\bWorklet\b/, /\bstyleSheets\b/, /\bcssRules\b/, /\.sheet\b/, /\bcreateElement\(\s*['"`](?:style|link)['"`]/, /\bcreateElementNS\([^)]*['"`](?:style|link)['"`]/, /\bstyleMap\b/i, /\bgetComputedStyle\b/, /\bCSS\s*\./,
  /\bCSSOM\b/, /\bwebkitAnimation\b/, /\banimationName\b/, /\banimationend\b/i, /\btransitionend\b/i, /\bmatchMedia\b/];
const dynamicStyleProblems = (text) => [...ANIMATION_APIS, ...STYLESHEET_APIS].filter((re) => re.test(text)).map(String);

test('no Web Animations API and no dynamic stylesheet API anywhere in the module: no animate(), getAnimations, KeyframeEffect, Animation, computedStyleMap, adoptedStyleSheets, CSSStyleSheet, insertRule, deleteRule, addRule, replaceSync, a style or link element made from code, registerProperty, paintWorklet or .sheet (reviewer mutant N21)', () => {
  assert.deepEqual(dynamicStyleProblems(plainCode), []);
  assert.deepEqual(dynamicStyleProblems(code), [], 'and in the whole code, the stylesheet builder included');
  // the card's one style element is the one the builder makes (mk(doc, 'style')), by name, and no other element of that kind is made from code
  assert.equal((code.match(/mk\(doc, 'style'\)/g) || []).length, 1);
  assert.equal((code.match(/mk\(doc, '(?:link|script)'/g) || []).length, 0);
});

test('no Web Animations API [r7]: the planted forms are each refused (negative controls: animate on the strip, getAnimations, KeyframeEffect, Animation, computedStyleMap, a stylesheet made, edited, adopted or registered, a style or link element made, a worklet, .sheet)', () => {
  const anchor = "    ui.geekBody.hidden = mode !== 'geek';";
  assert.equal(plainCode.split(anchor).length - 1, 1, 'the anchor is found once');
  const forms = [
    "    if (mode === 'geek' && typeof ui.strip.animate === 'function') ui.strip.animate([{ opacity: 0 }, { opacity: 0 }], { duration: 1e9, fill: 'forwards' });",
    "    ui.strip.animate([{ opacity: 0 }], 1);",
    "    for (const a of ui.strip.getAnimations()) a.pause();",
    "    new KeyframeEffect(ui.strip, [{ opacity: 0 }], 1);",
    "    new Animation();",
    "    void ui.strip.computedStyleMap;",
    "    this.ownerDocument.adoptedStyleSheets = [];",
    "    const s = new CSSStyleSheet();",
    "    ui.shell.sheet.insertRule('a{}');",
    "    ui.shell.sheet.deleteRule(0);",
    "    ui.shell.sheet.addRule('a', 'b');",
    "    ui.shell.sheet.replaceSync('a{}');",
    "    CSS.registerProperty({ name: '--x' });",
    "    const st = this.ownerDocument.createElement('style');",
    "    const lk = this.ownerDocument.createElement('link');",
    "    CSS.paintWorklet.addModule('x');",
    "    void ui.shell.sheet;",
    "    ui.strip.addEventListener('animationend', () => {});",
    "    window.matchMedia('(min-width: 1px)');",
  ];
  assert.deepEqual(dynamicStyleProblems(plainCode), [], 'the real source is clean by these same rules');
  for (const f of forms) assert.notDeepEqual(dynamicStyleProblems(plainCode.replace(anchor, () => `${anchor}\n${f}`)), [], f);
});

// ---------------------------------------------------------------------------------------------------------------------------
// Review round 8 ([r8]). The animation net of round 7 refused the NAME of the Web Animations and stylesheet APIs in the source, and two reviewer mutants passed every node suite all the same: M38 builds the name from pieces
// (`const fn = 'ani' + 'mate'; ui.strip[fn](...)`), M40b finds it by walking the prototype chain (`Object.getPrototypeOf` and `Object.getOwnPropertyNames`). The class is "a member is reached by something that is not its
// name", so these pins read the STRUCTURE (test/member-guard.mjs): (1) every computed member access whose key is not a literal is pinned, (2) the prototype chain, descriptors and inherited keys are never touched, (3) no
// string of the module is the name of a tripwire member. The behavioural net (the tripwires of minidom.mjs, asserted after every element test and step by step in both modes) stands behind them.
// ---------------------------------------------------------------------------------------------------------------------------
// every computed member access of the card whose key is not a literal, by receiver and key as written (a count after x). None of them reaches a DOM object by a name that is not written: the lookups in plain tables
// (status words, icons, severities, the rule table), in plain data (an attribute by its key, a state by its id) and the three of the mode switch (the two buttons of the switch, by mode). A new one is refused until
// a person has decided it and edited this list in the same commit.
const COMPUTED_ACCESSES = [
  'ICON_SHAPES[name]', 'PRETEST[i] x4', 'PRIORITY_RANK[a.priority]', 'PRIORITY_RANK[b.priority]', 'RULES[i]', 'RULE_PRETESTS[reason]', 'SEVERITY_RANK[x.severity]', 'SEVERITY_RANK[y.severity]',
  'SEVERITY_WORDS[a.severity]', 'STATUS_HELP[s]', 'STATUS_ICON[r.status]', 'STATUS_ICON[s]', 'STATUS_ICON[status]', 'STATUS_VAR[s]', 'STATUS_WORD[f]', 'STATUS_WORD[r.status]', 'STATUS_WORD[s] x3',
  'STATUS_WORD[status]', 'a[k] x2', 'alertInputs[a.entity_id]', 'attrs[k] x2', 'c[k] x3', 'c[s] x6', 'card[key]', 'counts[r.status]', 'counts[s]', 'input.attributes[when.attribute]', 'input[k] x2',
  'inputs[a.entity_id]', 'node[k] x2', 'opts[mode]', 'order[(i + 1) % order.length]', 'order[(i + order.length - 1) % order.length]', 'order[order.length - 1]', 'out[k]', 'out[shown]', 'red[top]', 's[k] x2',
  'st[a.entity_id]', 'st[job.id]', 'states[id] x2', 'this._ui.opts[next]', 'this.filters[name]', 'tokens[i + 1]', 'tokens[i] x3', 'tokens[tokens.length - 1] x3', 'ui.opts[m] x2', 'v[i]', 'v[k] x3',
  'value[k]', 'value[rest]', 'verdict[i] x2', 'was.flags[i]',
];

test('computed member access [r8]: every computed access whose key is not a literal is pinned, by receiver and key (reviewer mutant M38: ui.strip[fn](...) with a name built from pieces); the only ones on a DOM object are the buttons of the mode switch', () => {
  assert.deepEqual(expressionAccesses(plainCode), COMPUTED_ACCESSES);
  const onDom = COMPUTED_ACCESSES.filter((a) => /(^|\.)(ui|strip|shell|el|root|_root|doc|host|this)\b/.test(a) && !/^(?:this\._ui\.opts|ui\.opts)\[/.test(a) && !/^this\.filters\[/.test(a));
  assert.deepEqual(onDom, [], 'no computed access on `ui`, the strip, the shell, an element, a root, the document or the host except the switch buttons and the filter table');
  // a string literal as a key is allowed (it is a written name, and the name rules read it) and there is one
  assert.equal(computedStringKeys(plainCode), 1);
});

const computedStringKeys = (text) => [...skeleton(text).matchAll(/[\w$)\]]\s*\[\s*(?:''|"")\s*\]/g)].length;

test('computed member access [r8]: the planted forms are each refused (negative controls: M38 a name built from pieces, a variable key, a key made of a call, a bracket on the strip, the shell, the host, a root, a child and a document)', () => {
  const anchor = "    ui.geekBody.hidden = mode !== 'geek';";
  assert.equal(plainCode.split(anchor).length - 1, 1, 'the anchor is found once');
  const forms = [
    "    { const fn = 'ani' + 'mate'; if (mode === 'geek' && typeof ui.strip[fn] === 'function') ui.strip[fn]([{ opacity: 0 }], { duration: 1e9 }); }",
    "    ui.strip['ani' + 'mate']([{ opacity: 0 }], 1);",
    "    ui.strip[['ani', 'mate'].join('')]([{ opacity: 0 }], 1);",
    "    const k = 'a'; ui.shell[k + 'nimate']([], 1);",
    "    this._root[mode]();",
    "    this[mode + 'x']();",
    "    ui.geekBody[mode].hidden = true;",
    "    ui.strip.parentNode[mode]();",
    "    this.ownerDocument[mode] = [];",
    "    ui.strip[`${'ani'}mate`]([], 1);",
    "    const P = ui.strip; P[String.fromCharCode(97)]();",
  ];
  assert.deepEqual(expressionAccesses(plainCode), COMPUTED_ACCESSES, 'the real source is the pinned one');
  for (const f of forms) {
    const planted = plainCode.replace(anchor, () => `${anchor}\n${f}`);
    assert.notDeepEqual(expressionAccesses(planted), COMPUTED_ACCESSES, f);
  }
  // and the controls: a literal-key bracket is not a computed access with an expression, an array literal is not an access at all, a regular expression and a template text are not code
  const calm = [
    "    const a1 = ui.opts['production'];", "    const a2 = [1, 2, 3];", "    for (const q of [1, 2]) void q;", "    const r1 = /[a-z]+/.test('x[y]');", "    const t1 = `a[b] ${mode} [c]`;", "    return [mode];",
  ];
  for (const f of calm) assert.deepEqual(expressionAccesses(plainCode.replace(anchor, () => `${anchor}\n${f}`)), COMPUTED_ACCESSES, f);
});

test('prototype walking [r8]: the prototype chain, property descriptors, inherited keys and a symbol are never touched anywhere in the module; the one use of a prototype is the hasOwn helper (reviewer mutant M40b: Object.getPrototypeOf and Object.getOwnPropertyNames find the animate member)', () => {
  assert.deepEqual(doorsIn(plainCode), []);
  assert.deepEqual(doorsIn(code), [], 'and in the whole code, the stylesheet builder included');
  assert.equal((plainCode.match(/Object\.prototype\.hasOwnProperty\.call/g) || []).length, 1, 'the hasOwn helper is the one place a prototype is named');
  assert.match(plainCode, /const hasOwn = \(o, k\) => Object\.prototype\.hasOwnProperty\.call\(o, k\);/);
  assert.doesNotMatch(plainCode, /\bfor\s*\(\s*(?:const|let|var)\s+\w+\s+in\b/, 'no loop over inherited keys');
  const anchor = "    ui.geekBody.hidden = mode !== 'geek';";
  const forms = [
    "    { let P = ui.strip; let k; while (P && !k) { P = Object.getPrototypeOf(P); if (P) k = Object.getOwnPropertyNames(P).find((n) => n.length === 7 && n.startsWith('anim')); } if (mode === 'geek' && k) P[k].call(ui.strip, [], 1); }",
    "    const P1 = Object.getPrototypeOf(Object.getPrototypeOf(ui.strip));",
    "    const N1 = Object.getOwnPropertyNames(ui.strip);",
    "    const D1 = Object.getOwnPropertyDescriptor(ui.strip, 'x');",
    "    const D2 = Object.getOwnPropertyDescriptors(ui.strip);",
    "    const S1 = Object.getOwnPropertySymbols(ui.strip);",
    "    const Q1 = ui.strip.__proto__;",
    "    const Q2 = ui.strip.constructor.prototype;",
    "    Object.setPrototypeOf(ui.strip, null);",
    "    Object.defineProperty(ui.strip, 'x', { value: 1 });",
    "    for (const k in ui.strip) void k;",
    "    const R1 = Reflect.ownKeys(ui.strip);",
    "    const Y1 = Symbol('x');",
    "    ui.strip.constructor.prototype.animate = null;",
  ];
  for (const f of forms) assert.notDeepEqual(doorsIn(plainCode.replace(anchor, () => `${anchor}\n${f}`)), [], f);
  // a string that says __proto__ is only text (the redactor shows the key as [__proto__]): it is not a door
  assert.deepEqual(doorsIn(plainCode.replace(anchor, () => `${anchor}\n    const T1 = '__proto__';`)), []);
});

test('tripwire names [r8]: no string, template or bracket of the module is the name of an animation, style-map or stylesheet member (the names the tripwires of the element tests watch)', () => {
  for (const name of TRIPWIRE_NAMES) {
    const quoted = new RegExp(`['"\`]${name}['"\`]`);
    assert.doesNotMatch(plainCode, quoted, `${name} as a string`);
    assert.doesNotMatch(plainCode, new RegExp(`\\b${name}\\b`), `${name} as a word`);
  }
  const anchor = "    ui.geekBody.hidden = mode !== 'geek';";
  for (const name of TRIPWIRE_NAMES) {
    for (const f of [`    const s1 = ui.strip['${name}'];`, `    const s2 = ui.strip.${name};`, `    const s3 = '${name}';`]) {
      const planted = plainCode.replace(anchor, () => `${anchor}\n${f}`);
      assert.ok(new RegExp(`\\b${name}\\b`).test(planted), f);
    }
  }
  assert.ok(TRIPWIRE_NAMES.length >= 10);
});

test('snapshot budget [r8]: the budget is made once per snapshot, charged for every entity that is read, decides before the cache is asked, and an entity that is not read is built with no parts (the wiring, by the source)', () => {
  assert.match(code, /snapshotChars: 2000000,/);
  assert.match(code, /nodeChars: 1,/);
  assert.match(code, /entityBaseChars: 250,/);
  assert.match(code, /entityIdChars: 255,/);
  const bs = topLevel('buildSnapshot');
  assert.equal((bs.match(/const budget = \{ left: LIMITS\.snapshotChars \};/g) || []).length, 1, 'one budget per snapshot, made from the limit');
  assert.equal((bs.match(/budget\.left -= row\.spent;/g) || []).length, 1, 'charged once per row');
  assert.match(bs, /makeRow\(src, state, nowMs, cat, job\.order, ledgerKey, isObj\(state\) && budget\.left <= 0\)/, 'the decision is made before the row is made, from the budget as it stands');
  assert.match(bs, /jobs\.sort\(\(a, b\) => a\.rank - b\.rank \|\| a\.order - b\.order\);/);
  assert.match(bs, /rank: cat\.alertIds\.has\(src\.entity_id\) \? 0 : src\.priority === 'headline' \? 1 : 2,/);
  assert.match(bs, /rank: cat\.alertIds\.has\(id\) \? 0 : 3,/);
  assert.ok(bs.indexOf('jobs.sort') < bs.indexOf('const budget ='), 'the order is fixed before the budget is spent');
  // the cache: a row that is not to be read never goes through it
  const mr = topLevel('makeRow');
  assert.ok(mr.indexOf('if (unread) return buildRow(') > 0 && mr.indexOf('if (unread) return buildRow(') < mr.indexOf('memo.get(holder)'), 'an unread row is made before, and without, the cache');
  // an entity that is not read has no parts: nothing of it is scanned
  const br = topLevel('buildRow');
  assert.match(br, /const parts = present && !unreadHere \? partsFor\(source, state, cat\) : null;/);
  // what an entity costs is kept with its parts
  assert.match(topLevel('partsFor'), /const spent = Math\.max\(LIMITS\.entityBaseChars, Math\.min\(LIMITS\.entityChars, LIMITS\.entityChars - opts\.scan\.left\) \+ work\.nodes \* LIMITS\.nodeChars\);/);
  assert.match(code, /order, unread: unreadHere, spent: parts \? parts\.spent : 0,/);
  // the id is read for every discovered entity, at most 255 characters, and costs the snapshot nothing
  assert.match(bs, /const display = job\.id\.length > LIMITS\.entityIdChars \? WITHHELD : redactString\(job\.id, 'note'\);/);
  // the alerts do not go through the budget: they are built from the raw states
  assert.match(bs, /alertInputs\[a\.entity_id\] = isObj\(s\)/);
  assert.ok(!/budget/.test(bs.slice(bs.indexOf('const alertInputs'))), 'the alert inputs are made with no budget in sight');
});

// ---------------------------------------------------------------------------------------------------------------------------
// Review round 9 ([r9]): THE RUNNER RULE needs to know which tests are about time. A test that asserts how LONG something took can fail under the parallel load of the mutation runner for no fault of the card, so the runner
// (mutations.test.mjs) runs a mutant whose only failing tests are of that kind again, alone, before it counts it as killed. It knows them by [wall-clock] in the title. This is the check that the tag is kept: every test of
// perf.test.mjs (the timing file; its helpers read the clock, so the tests do not show it) and every test of any other file whose own text reads the clock carries it.
// ---------------------------------------------------------------------------------------------------------------------------
test('test files [r9]: every test that is about time (all of perf.test.mjs, and any test that reads the clock) carries the wall-clock tag in its title, so that the mutation runner can tell a timing failure from a behavioural one', () => {
  const dir = path.join(cardDir, 'test');
  const clock = new RegExp(['\\bperformance\\.', 'now\\(\\)|\\bDate\\.', 'now\\(\\)'].join(''));
  const missing = [];
  let tagged = 0;
  let timed = 0;
  for (const file of readdirSync(dir).filter((x) => x.endsWith('.test.mjs') && x !== 'mutations.test.mjs')) {
    const text = readFileSync(path.join(dir, file), 'utf8');
    const starts = [...text.matchAll(/^[ \t]*test(?:\.\w+)?\(/gm)].map((m) => m.index);
    starts.forEach((at, i) => {
      const body = text.slice(at, i + 1 < starts.length ? starts[i + 1] : text.length);
      const first = body.split('\n')[0];
      const has = first.includes('[wall-clock]');
      const needs = file === 'perf.test.mjs' || clock.test(body);
      if (has) tagged += 1;
      if (needs) timed += 1;
      if (needs && !has) missing.push(`${file}: ${first.slice(0, 90)}`);
      if (has && !needs) missing.push(`${file}: tagged but not about time: ${first.slice(0, 90)}`);
    });
  }
  assert.deepEqual(missing, [], 'a test about time is not tagged (or a tag is on a test that is not about time)');
  assert.ok(tagged >= 15 && tagged === timed, `${tagged} tagged, ${timed} about time`);
});
