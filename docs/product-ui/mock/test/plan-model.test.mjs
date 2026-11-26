// Offline checks for the Energy Plan design mock (docs/product-ui/mock/index.html).
// Run from the repository root:  node --test docs/product-ui/mock/test/plan-model.test.mjs
// It loads only the page's pure plan-model script into an isolated VM context (no DOM, no network) and checks:
//   1. every cross-card acceptance check in PlanModel.runChecks() passes;
//   2. a few direct properties of the model (bounds, the 10 % floor, no 5 % target, read-only previews);
//   3. the page itself has no network or Home Assistant access path and no external resource.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const html = readFileSync(fileURLToPath(new URL('../index.html', import.meta.url)), 'utf8');

function loadModel() {
  const m = /<script id="plan-model">([\s\S]*?)<\/script>/.exec(html);
  assert.ok(m, 'script#plan-model not found');
  const ctx = vm.createContext({});
  vm.runInContext(m[1], ctx, { filename: 'plan-model.js' });
  assert.ok(ctx.PlanModel, 'PlanModel not defined');
  return ctx.PlanModel;
}
const M = loadModel();

test('both page scripts compile (a syntax error would leave the page blank)', () => {
  for (const id of ['plan-model', 'ui']) {
    const m = new RegExp(`<script id="${id}">([\\s\\S]*?)<\\/script>`).exec(html);
    assert.ok(m, `script#${id} not found`);
    assert.doesNotThrow(() => new vm.Script(m[1], { filename: `${id}.js` }), `script#${id} does not compile`);
  }
});

test('every cross-card check passes', () => {
  const results = M.runChecks();
  assert.ok(results.length >= 20, `expected at least 20 checks, got ${results.length}`);
  // The results come from another VM realm, so compare plain values, not array identity.
  const failed = Array.from(results).filter((r) => !r.pass).map((r) => `${r.id} ${r.name}: ${r.detail}`);
  assert.equal(failed.length, 0, failed.join('\n'));
});

test('the export floor is 10 % and 5 % is refused, not clamped', () => {
  const s = M.newState();
  for (const v of [0, 5, 9]) {
    const r = M.edit(s, 'export.stopSoc', v);
    assert.equal(r.ok, false);
    assert.match(r.error, /10 %/);
    assert.equal(r.state, s);
  }
  assert.equal(M.edit(s, 'export.stopSoc', 10).ok, true);
  assert.equal(M.LIMITS.exportStopSocMin, 10);
});

test('the finish-before-end buffer is editable 0-120 min in 5-minute steps', () => {
  const s = M.newState();
  for (const v of [0, 5, 60, 115, 120]) assert.equal(M.edit(s, 'charge.bufferMin', v).ok, true, `buffer ${v}`);
  for (const v of [-5, 3, 125, 240]) assert.equal(M.edit(s, 'charge.bufferMin', v).ok, false, `buffer ${v}`);
});

test('editing never changes the readback or the saved plan', () => {
  const s = M.newState();
  const before = JSON.stringify({ rb: s.readback, saved: s.saved });
  let r = M.edit(s, 'charge.bufferMin', 30);
  r = M.edit(r.state, 'export.gapMin', 90);
  r = M.edit(r.state, 'profile', 'summer');
  assert.equal(JSON.stringify({ rb: r.state.readback, saved: r.state.saved }), before);
  assert.ok(r.state.draft);
});

test('net export never exceeds the hardware-tested battery ceiling', () => {
  for (const soc of [40, 60, 80, 95, 100]) {
    for (const fin of ['20:00', '21:00', '22:30', '23:00']) {
      let st = M.setCtx(M.newState(), 'socNow', soc);
      let r = M.edit(st, 'export.finishMode', 'at_time');
      r = M.edit(r.state, 'export.finishAt', fin);
      r = M.edit(r.state, 'export.stopSoc', 10);
      const d = M.derive(r.state);
      if (!d.export.refusals.length) assert.ok(d.export.battW <= M.LIMITS.provenExportCeilingW, `soc ${soc} fin ${fin}: ${d.export.battW}`);
    }
  }
});

test('a slot table that is not one 24-hour cycle pauses planning', () => {
  let s = M.newState();
  s = M.simulateExternalEdit(s, 3, 'start', '03:00');
  const d = M.derive(s);
  assert.equal(d.touCheck.ok, false);
  assert.ok(d.compiled.paused);
  assert.equal(d.compiled.actions.length, 0);
});

test('the page has no network, Home Assistant or external-resource path', () => {
  const page = html;
  for (const bad of [/\bfetch\s*\(/, /XMLHttpRequest/, /WebSocket/, /EventSource/, /sendBeacon/, /callService/, /callWS/, /\bhass\b/, /\bimport\s*\(/,
    /url\(\s*['"]?(https?:)?\/\//i, /@import/i, /<link\b/i, /<iframe\b/i, /<form\b/i, /window\.open\s*\(/]) {
    assert.doesNotMatch(page, bad, `found ${bad}`);
  }
  assert.doesNotMatch(page, /(src|href)\s*=\s*["']?(https?:)?\/\//i, 'external resource reference');
  assert.match(page, /Content-Security-Policy" content="default-src 'none'/);
  assert.doesNotMatch(page, /\b(?:\d{1,3}\.){3}\d{1,3}\b/, 'an IP-address-like string');
});
