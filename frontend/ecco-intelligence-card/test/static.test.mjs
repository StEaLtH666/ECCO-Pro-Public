// Source-level pins (node side; the Python pin suite tools/tests/test_intelligence_card.py repeats them for CI, which runs
// no Node): no write, network or dynamic-code API; hass.states only; no external resource; the licence; the folder.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';
import { cardDir } from './helpers.mjs';

const src = readFileSync(path.join(cardDir, 'ecco-intelligence-card.js'), 'utf8');
const code = src.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:'"`\\])\/\/.*$/gm, '$1');

test('no write, network, storage or dynamic-code API in the module (comments stripped)', () => {
  const banned = ['callService', 'callWS', 'callApi', 'sendMessage', 'subscribeEvents', 'subscribeMessage', 'XMLHttpRequest',
    'WebSocket', 'EventSource', 'sendBeacon', 'localStorage', 'sessionStorage', 'indexedDB', 'postMessage', 'document.cookie',
    'perform_action', 'call_service', 'hass-action', 'hass-more-info', 'dispatchEvent', 'button.press', 'persistent_notification',
    'turn_on', 'turn_off', 'toggle', 'set_value', 'connection', 'innerText'];
  const hits = banned.filter((t) => code.includes(t));
  assert.deepEqual(hits, []);
  for (const re of [/\bfetch\s*\(/, /\beval\s*\(/, /\bnew\s+Function\b/, /\bimport\s*\(/, /\.press\s*\(/, /\bsetTimeout\s*\(/,
    /\brequestAnimationFrame\s*\(/, /\bReflect\b/, /\bglobalThis\b/, /\bdocument\b/]) {
    assert.doesNotMatch(code, re);
  }
});

test('hass: only hass.states is read, and the hass object is stored as given (never replaced by a connection)', () => {
  assert.deepEqual([...new Set([...code.matchAll(/\bh\.(\w+)/g)].map((m) => m[1]))], ['states']);
  assert.equal((code.match(/\bconst h = this\._hass;/g) || []).length, 1, 'the one place the hass object is read');
  assert.doesNotMatch(code, /hass\??\.(?!states\b)\w/);
  assert.equal((code.match(/setInterval\s*\(/g) || []).length, 1, 'the one re-render tick');
});

test('no external resource: no URL, @import, url(), font-face or image', () => {
  assert.doesNotMatch(src, /https?:\/\//);
  assert.doesNotMatch(src, /@import|url\(|@font-face|<img|<link|<script/i);
});

test('package.json: GPL-3.0-or-later, private, module, no dependency of any kind', () => {
  const pkg = JSON.parse(readFileSync(path.join(cardDir, 'package.json'), 'utf8'));
  assert.equal(pkg.license, 'GPL-3.0-or-later');
  assert.equal(pkg.private, true);
  assert.equal(pkg.type, 'module');
  assert.equal(pkg.name, 'ecco-intelligence-card');
  for (const k of ['dependencies', 'devDependencies', 'peerDependencies', 'optionalDependencies', 'bundledDependencies']) {
    assert.equal(pkg[k], undefined, k);
  }
});

test('the folder: text files only, LF only, no build output or lockfile', () => {
  const walk = (d) => readdirSync(d).flatMap((n) => (statSync(path.join(d, n)).isDirectory() ? walk(path.join(d, n)) : [path.join(d, n)]));
  for (const f of walk(cardDir)) {
    const b = readFileSync(f);
    assert.ok(!b.includes(0), `${f}: binary`);
    assert.ok(!b.includes(Buffer.from('\r\n')), `${f}: CRLF`);
    assert.doesNotMatch(path.basename(f), /\.(png|jpe?g|gif|webp|ico|woff2?|ttf|map)$|^package-lock\.json$/);
  }
});
