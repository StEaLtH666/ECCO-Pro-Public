// The logic of the headless-browser check of the alert strip, tested OFFLINE with synthetic measurements (review round 3). The browser itself is exercised by
// `node preview/check-strip.mjs` (opt-in; it prints SKIPPED loudly when no Chrome or Edge is installed) and by `node preview/check-strip.mjs --selftest`.
// What is tested here: the colour and contrast arithmetic, that a healthy measurement passes every check, that a measurement of a strip hidden in each way the
// reviewers found fails at least one check (so the check cannot pass what it was written to catch), that the two modes are compared, that the browser search
// order is right, and that the self-test's table of broken cards cannot rot (every entry's text is found once in the card; every stylesheet entry is also
// refused by the static nets, so the static net and the browser net agree).
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { cardDir, loadCard } from './helpers.mjs';
import { parseColour, over, luminance, contrastRatio, effectiveBackground, evaluateState, compareModes, evaluateAll } from '../preview/strip-check-lib.mjs';
import { findBrowser, BROKEN } from '../preview/check-strip.mjs';
import { pinProblems, stripProblems } from './css-guard.mjs';

const { STYLE } = await loadCard('strip-check');

const approx = (a, b, d = 0.02) => assert.ok(Math.abs(a - b) <= d, `${a} is not within ${d} of ${b}`);

test('parseColour reads what the browser reports, and nothing else', () => {
  assert.deepEqual(parseColour('rgb(1, 2, 3)'), { r: 1, g: 2, b: 3, a: 1 });
  assert.deepEqual(parseColour('rgba(1, 2, 3, 0.5)'), { r: 1, g: 2, b: 3, a: 0.5 });
  assert.deepEqual(parseColour('rgb(1 2 3 / 50%)'), { r: 1, g: 2, b: 3, a: 0.5 });
  assert.deepEqual(parseColour('rgba(0, 0, 0, 0)'), { r: 0, g: 0, b: 0, a: 0 });
  assert.deepEqual(parseColour('transparent'), { r: 0, g: 0, b: 0, a: 0 });
  assert.deepEqual(parseColour('color(srgb 0.5 0.25 1 / 0.5)'), { r: 127.5, g: 63.75, b: 255, a: 0.5 });
  for (const bad of ['', 'red', '#fff', 'rgb(1,2)', null, undefined, 5, 'hsl(0 0% 0%)']) assert.equal(parseColour(bad), null, String(bad));
});

test('contrast arithmetic: black on white is 21, equal colours are 1, the usual grey borderline is where WCAG puts it', () => {
  const black = { r: 0, g: 0, b: 0, a: 1 };
  const white = { r: 255, g: 255, b: 255, a: 1 };
  approx(contrastRatio(black, white), 21, 0.001);
  approx(contrastRatio(white, white), 1, 0.001);
  approx(contrastRatio({ r: 119, g: 119, b: 119, a: 1 }, white), 4.48, 0.02);
  approx(contrastRatio({ r: 118, g: 118, b: 118, a: 1 }, white), 4.54, 0.02);
  approx(luminance(white), 1, 0.0001);
  approx(luminance(black), 0, 0.0001);
});

test('compositing: a half-transparent colour over another, and the colour behind text from its ancestors', () => {
  const c = over({ r: 255, g: 0, b: 0, a: 0.5 }, { r: 0, g: 0, b: 255, a: 1 });
  approx(c.r, 127.5, 0.01);
  approx(c.b, 127.5, 0.01);
  assert.equal(c.a, 1);
  assert.deepEqual(over({ r: 9, g: 9, b: 9, a: 0 }, { r: 1, g: 2, b: 3, a: 1 }), { r: 1, g: 2, b: 3, a: 1 });
  // nearest first: the text sits on a transparent span, in an opaque card, in a page
  const bg = effectiveBackground(['rgba(0, 0, 0, 0)', 'rgb(23, 33, 51)', 'rgb(11, 18, 32)']);
  assert.deepEqual([Math.round(bg.r), Math.round(bg.g), Math.round(bg.b), bg.a], [23, 33, 51, 1]);
  const none = effectiveBackground(['rgba(0, 0, 0, 0)']);
  assert.deepEqual([none.r, none.g, none.b], [255, 255, 255], 'a page with no background paints on white');
});

// ---- a healthy synthetic measurement, and the ways it can go wrong ----
const R = (x, y, width, height) => ({ x, y, width, height });
const NEUTRAL_NODE = { tag: 'div', cls: '', isHost: false, display: 'grid', visibility: 'visible', contentVisibility: 'visible', opacity: 1, transform: 'none', rotate: 'none', scale: 'none', translate: 'none',
  filter: 'none', clipPath: 'none', maskImage: 'none', backdropFilter: 'none', overflowX: 'visible', overflowY: 'visible', contain: 'none', rect: R(12, 12, 390, 400) };
function healthy(over = {}) {
  const line = (id, quiet = false) => ({ id, quiet, part: 'head', text: quiet ? 'No active alerts.' : 'Critical: The self-test failed.', textBox: R(60, 90, 200, 20), fontSize: '14px', lineHeight: '20px',
    color: 'rgb(27, 35, 48)', textFill: 'rgb(27, 35, 48)', bgLayers: ['rgb(255, 255, 255)', 'rgba(0, 0, 0, 0)'], hit: { inside: true, tag: 'div.alert' }, icon: { color: 'rgb(168, 32, 26)', rect: R(24, 88, 22, 22) } });
  return {
    id: 'alerts|light|ha|production|w390|v1084', scenario: 'alerts', theme: 'light', vars: 'ha', mode: 'production', width: 390, expectAlerts: null, viewport: { w: 1084, h: 1500 },
    host: R(12, 12, 390, 400), shell: { mode: 'production' },
    strip: { present: true, rect: R(12, 80, 390, 60), chain: [{ ...NEUTRAL_NODE, tag: 'div', cls: 'alerts', rect: R(12, 80, 390, 60) }, { ...NEUTRAL_NODE, tag: 'div', cls: 'shell' }, { ...NEUTRAL_NODE, tag: 'ecco-mode-shell', isHost: true, display: 'block' }] },
    alerts: [line('a1'), { ...line('a1'), part: 'action', text: 'What to do: wait.', icon: null, textBox: R(60, 112, 200, 20) }],
    bodies: { production: { shown: true, rect: R(12, 150, 390, 200) }, geek: { shown: false, rect: R(0, 0, 0, 0) } },
    ...over,
  };
}
const failing = (m) => evaluateState(m).filter((c) => !c.ok).map((c) => c.name);
const withStrip = (patch) => { const m = healthy(); m.strip = { ...m.strip, ...patch }; return m; };
const withChain0 = (patch) => { const m = healthy(); m.strip.chain = [{ ...m.strip.chain[0], ...patch }, ...m.strip.chain.slice(1)]; return m; };
const withLine = (patch) => { const m = healthy(); m.alerts = m.alerts.map((a, i) => (i === 0 ? { ...a, ...patch } : a)); return m; };

test('a healthy strip passes every check, and the report names what was looked at', () => {
  const checks = evaluateState(healthy());
  assert.ok(checks.length >= 30, `${checks.length} checks`);
  assert.deepEqual(checks.filter((c) => !c.ok), []);
  assert.ok(checks.some((c) => /opacity/.test(c.name)) && checks.some((c) => /contrast/.test(c.name)) && checks.some((c) => /same|covers/.test(c.name)));
});

test('a strip that is hidden, moved, shrunk, faded, filtered, clipped, covered or unreadable fails at least one check, whichever way it was done (negative controls)', () => {
  const cases = {
    'no strip at all': { ...healthy(), strip: { present: false } },
    'zero height': withStrip({ rect: R(12, 80, 390, 0) }),
    'a 2 px sliver': withStrip({ rect: R(12, 80, 390, 2) }),
    'zero width': withStrip({ rect: R(12, 80, 0, 60) }),
    'below the viewport (order, margin)': withStrip({ rect: R(12, 4000, 390, 60) }),
    'left of the viewport (negative margin)': withStrip({ rect: R(-3000, 80, 390, 60) }),
    'right of its card (offset)': withStrip({ rect: R(900, 80, 390, 60) }),
    'shifted sideways by 60 px': withStrip({ rect: R(72, 80, 390, 60) }),
    'display none on an ancestor': withChain0({ display: 'none' }),
    'visibility hidden': withChain0({ visibility: 'hidden' }),
    'content-visibility hidden': withChain0({ contentVisibility: 'hidden' }),
    'opacity .02': withChain0({ opacity: 0.02 }),
    'opacity .5': withChain0({ opacity: 0.5 }),
    'transform rotateX': withChain0({ transform: 'matrix3d(1, 0, 0, 0, 0, 0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 1)' }),
    'transform scale': withChain0({ transform: 'matrix(0.001, 0, 0, 0.001, 0, 0)' }),
    'rotate property': withChain0({ rotate: '90deg' }),
    'scale property': withChain0({ scale: '0.001' }),
    'translate property': withChain0({ translate: '0px -999px' }),
    'blur filter': withChain0({ filter: 'blur(40px)' }),
    'clip-path': withChain0({ clipPath: 'circle(0px at 50% 50%)' }),
    'mask': withChain0({ maskImage: 'linear-gradient(transparent, transparent)' }),
    'backdrop filter': withChain0({ backdropFilter: 'blur(99px)' }),
    'size containment': withChain0({ contain: 'size' }),
    'clipped by an ancestor': (() => { const m = healthy(); m.strip.chain[1] = { ...m.strip.chain[1], overflowX: 'hidden', overflowY: 'hidden', rect: R(12, 12, 390, 20) }; return m; })(),
    'no lines': { ...healthy(), alerts: [] },
    'a tiny font': withLine({ fontSize: '0.01px' }),
    'an 11 px font': withLine({ fontSize: '11px' }),
    'line height 0': withLine({ lineHeight: '0px' }),
    'transparent text': withLine({ color: 'rgba(0, 0, 0, 0)', textFill: 'rgba(0, 0, 0, 0)' }),
    'transparent text fill only': withLine({ textFill: 'rgba(0, 0, 0, 0)' }),
    'text the colour of its background': withLine({ color: 'rgb(255, 255, 255)', textFill: 'rgb(255, 255, 255)' }),
    'faint text (3:1)': withLine({ color: 'rgb(150, 150, 150)', textFill: 'rgb(150, 150, 150)' }),
    'a text box of nothing': withLine({ textBox: R(60, 90, 0, 0) }),
    'a text box outside the strip': withLine({ textBox: R(60, 900, 200, 20) }),
    'covered by another element': withLine({ hit: { inside: false, tag: 'div.top' } }),
    'empty text': withLine({ text: '  ' }),
    'an icon with no size': withLine({ icon: { color: 'rgb(168, 32, 26)', rect: R(24, 88, 0, 0) } }),
    'an invisible icon': withLine({ icon: { color: 'rgba(0, 0, 0, 0)', rect: R(24, 88, 22, 22) } }),
    'a low-contrast icon': withLine({ icon: { color: 'rgb(250, 250, 250)', rect: R(24, 88, 22, 22) } }),
    'the shell is not in the mode asked for': { ...healthy(), shell: { mode: 'geek' } },
    'the Production body is hidden in Production': { ...healthy(), bodies: { production: { shown: false, rect: R(0, 0, 0, 0) }, geek: { shown: false, rect: R(0, 0, 0, 0) } } },
    'the strip sits below the Production body': { ...healthy(), bodies: { production: { shown: true, rect: R(12, 10, 390, 60) }, geek: { shown: false, rect: R(0, 0, 0, 0) } } },
  };
  for (const [what, m] of Object.entries(cases)) assert.notDeepEqual(failing(m), [], `the check accepted: ${what}`);
  // the expected alerts count is checked when the data calls for a number
  assert.deepEqual(failing({ ...healthy(), expectAlerts: 1, alerts: [{ ...healthy().alerts[0] }] }), []);
  assert.notDeepEqual(failing({ ...healthy(), expectAlerts: 3 }), []);
});

test('Geek Mode: the Geek body must be shown and below the strip; a strip pushed below it fails', () => {
  const geek = healthy({ mode: 'geek', shell: { mode: 'geek' }, bodies: { production: { shown: false, rect: R(0, 0, 0, 0) }, geek: { shown: true, rect: R(12, 150, 390, 900) } } });
  assert.deepEqual(failing(geek), []);
  const pushed = { ...geek, strip: { ...geek.strip, rect: R(12, 1100, 390, 60) } };
  assert.ok(failing(pushed).some((n) => /above the Geek body|inside the viewport/.test(n)));
  const noGeek = { ...geek, bodies: { production: { shown: false, rect: R(0, 0, 0, 0) }, geek: { shown: false, rect: R(0, 0, 0, 0) } } };
  assert.ok(failing(noGeek).some((n) => /Geek body is shown/.test(n)));
});

test('the two modes are compared: the same box and the same lines, or the pair fails', () => {
  const p = healthy();
  const g = healthy({ mode: 'geek', shell: { mode: 'geek' } });
  assert.deepEqual(compareModes(p, g).filter((c) => !c.ok), []);
  const moved = healthy({ mode: 'geek', shell: { mode: 'geek' }, strip: { ...p.strip, rect: R(12, 400, 390, 60) } });
  assert.ok(compareModes(p, moved).some((c) => !c.ok && /same box/.test(c.name)));
  const resized = healthy({ mode: 'geek', shell: { mode: 'geek' }, strip: { ...p.strip, rect: R(12, 80, 390, 30) } });
  assert.ok(compareModes(p, resized).some((c) => !c.ok));
  const fewer = healthy({ mode: 'geek', shell: { mode: 'geek' }, alerts: p.alerts.slice(0, 1) });
  assert.ok(compareModes(p, fewer).some((c) => !c.ok && /same lines/.test(c.name)));
  const reworded = healthy({ mode: 'geek', shell: { mode: 'geek' }, alerts: p.alerts.map((a) => ({ ...a, text: `${a.text}!` })) });
  assert.ok(compareModes(p, reworded).some((c) => !c.ok));
  const lineMoved = healthy({ mode: 'geek', shell: { mode: 'geek' }, alerts: p.alerts.map((a) => ({ ...a, textBox: R(60, 300, 200, 20) })) });
  assert.ok(compareModes(p, lineMoved).some((c) => !c.ok && /each line/.test(c.name)));
});

test('evaluateAll pairs each Production state with its Geek twin and counts what failed; a missing twin fails', () => {
  const p = healthy();
  const g = healthy({ id: 'alerts|light|ha|geek|w390|v1084', mode: 'geek', shell: { mode: 'geek' }, bodies: { production: { shown: false, rect: R(0, 0, 0, 0) }, geek: { shown: true, rect: R(12, 150, 390, 900) } } });
  const ok = evaluateAll([p, g]);
  assert.equal(ok.failed, 0);
  assert.equal(ok.states.length, 2);
  assert.equal(ok.pairs.length, 1);
  assert.ok(ok.total > 60);
  const lone = evaluateAll([p]);
  assert.ok(lone.failed > 0, 'a Production state with no Geek twin is a failure, not a pass');
  const bad = evaluateAll([p, { ...g, strip: { ...g.strip, rect: R(12, 80, 390, 0) } }]);
  assert.ok(bad.failed > 0);
});

test('the browser search: ECCO_CHROME first, then the standard places; none means null (the caller prints SKIPPED)', () => {
  const env = { ProgramFiles: 'C:\\Program Files', 'ProgramFiles(x86)': 'C:\\Program Files (x86)', LOCALAPPDATA: 'C:\\Local' };
  const has = (set) => (p) => set.includes(p);
  assert.equal(findBrowser({ ...env, ECCO_CHROME: 'D:\\mine\\chrome.exe' }, has(['D:\\mine\\chrome.exe', path.join('C:\\Program Files', 'Google', 'Chrome', 'Application', 'chrome.exe')])), 'D:\\mine\\chrome.exe');
  assert.equal(findBrowser(env, has([path.join('C:\\Program Files', 'Google', 'Chrome', 'Application', 'chrome.exe')])), path.join('C:\\Program Files', 'Google', 'Chrome', 'Application', 'chrome.exe'));
  assert.equal(findBrowser(env, has([path.join('C:\\Program Files (x86)', 'Microsoft', 'Edge', 'Application', 'msedge.exe')])), path.join('C:\\Program Files (x86)', 'Microsoft', 'Edge', 'Application', 'msedge.exe'));
  assert.equal(findBrowser({}, has(['/usr/bin/chromium'])), '/usr/bin/chromium');
  assert.equal(findBrowser({ ECCO_CHROME: 'D:\\gone\\chrome.exe' }, has([])), null);
  assert.equal(findBrowser(env, has([])), null);
});

test('the self-test table cannot rot: every broken copy changes the card in exactly one place, and every stylesheet change is also refused by the pin and by the semantic net', () => {
  const real = readFileSync(path.join(cardDir, 'ecco-mode-shell.js'), 'utf8');
  assert.ok(BROKEN.length >= 25);
  assert.equal(new Set(BROKEN.map((b) => b[0])).size, BROKEN.length, 'unique names');
  const pin = JSON.parse(readFileSync(path.join(cardDir, 'test', 'fixtures', 'style.pin.json'), 'utf8'));
  const modes = new Set(['.switch[data-mode="geek"] .thumb']);
  const strips = new Set(['.alert', '.alert-action', '.alert-head', '.alert.quiet', '.alert.quiet>.ico', '.alert>.ico', '.alert[data-severity="critical"]', '.alert[data-severity="critical"]>.ico',
    '.alert[data-severity="warning"]', '.alert[data-severity="warning"]>.ico', '.alerts']);
  let stylesheetOnes = 0;
  for (const [id, find, repl] of BROKEN) {
    assert.equal(real.split(find).length - 1, 1, `${id}: the text to break is found once`);
    assert.notEqual(find, repl, id);
    const broken = real.replace(find, () => repl);
    const inStyle = STYLE.includes(find);
    if (!inStyle) continue;
    stylesheetOnes += 1;
    const css = STYLE.replace(find, () => repl);
    assert.notDeepEqual(pinProblems(css, pin), [], `${id}: the pin accepted it`);
    assert.notEqual(broken, real);
    // the semantic net sees the rules that reach the strip. Two kinds are the documented limit of reading CSS and are caught by the pin and by the browser: a colour
    // choice that is allowed on its own but unreadable next to another, and a rule on a NEIGHBOUR of the strip (the element above it) that overlaps it
    if (!/text and surface set to the same|text colour equal to the background|faint text colour|covered by a positioned block/.test(id)) {
      assert.notDeepEqual(stripProblems(css, { modeSelectors: modes, stripSelectors: strips }), [], `${id}: the semantic net accepted it`);
    }
  }
  assert.ok(stylesheetOnes >= 20, `${stylesheetOnes} stylesheet entries`);
});
