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
