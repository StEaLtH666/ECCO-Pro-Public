// Source-level pins (node side). The card must have no write, network, storage, history or dynamic-code API; read hass.states,
// hass.locale and hass.themes only; build every node with node APIs (never markup); keep the mode in one controller and nowhere
// else; use ONE snapshot adapter and ONE alert-strip renderer; carry no URL or external resource; and ship only text, as LF.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';
import { cardDir, CARD_PATH, cardUrl } from './helpers.mjs';

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

const ALERT_TOKEN = /\.alerts?\b|data-ecco-alert-strip|data-alert|role=["']?alert/;
const MODE_TOKEN = /data-mode|data-ecco-body|data-ecco-mode|data-geek|data-production/;
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
