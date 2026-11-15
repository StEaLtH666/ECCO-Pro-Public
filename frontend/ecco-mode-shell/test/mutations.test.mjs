// Mutation proof: every acceptance case that needs one is shown to FAIL without its behaviour. Each mutant is a small,
// deliberate break of the card (written to a scratch copy in the OS temp folder, never in the repository); the other
// test files are run against it with ECCO_MODE_SHELL_PATH pointing at the copy, and the mutant is KILLED when that run
// fails. A mutant whose target text is not found exactly once is itself a failure (the table would otherwise rot silently).
// AC5, AC6, AC10 and AC13 have at least six mutants each (this file asserts it); the others have at least one.
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { cardDir } from './helpers.mjs';

const nested = process.env.ECCO_MODE_SHELL_PATH !== undefined || process.env.ECCO_SKIP_MUTATIONS === '1';
const REAL = path.join(cardDir, 'ecco-mode-shell.js');
const SUITES = ['core.test.mjs', 'element.test.mjs', 'static.test.mjs', 'coverage.test.mjs'].map((f) => path.join(cardDir, 'test', f));

/** sub(find, replace[, all]): replace the one occurrence of `find` (or every occurrence with all = true). */
const sub = (find, replace, all = false) => (s) => {
  const n = s.split(find).length - 1;
  if (n === 0 || (n > 1 && !all)) throw new Error(`mutation target found ${n} times: ${find.slice(0, 80)}`);
  return s.split(find).join(replace);
};
const chain = (...fs) => (s) => fs.reduce((acc, f) => f(acc), s);

const MUTANTS = [
  // ---- AC1 default Production
  { id: 'AC1-default-geek', ac: 'AC1', note: 'the controller starts in Geek Mode', f: sub('let mode = DEFAULT_MODE;', "let mode = 'geek';") },
  // ---- AC2 / AC3 reset rules
  { id: 'AC3-no-location-listener', ac: 'AC3', note: 'no reset on a location change', f: sub("window.addEventListener('location-changed', this._onLocation);", '') },
  { id: 'AC3-reset-on-same-path', ac: 'AC3', note: 'a location event on the same path resets (over-reset)', f: sub('if (this._pathNow() !== this._entryPath) this._ctl.reset();', 'this._ctl.reset();') },
  { id: 'AC3-no-reset-on-disconnect', ac: 'AC3', note: 'disconnect keeps the mode', f: sub('    this._connected = false;\n    this._ctl.reset();', '    this._connected = false;') },
  { id: 'AC3-no-reset-on-entry', ac: 'AC3', note: 'connect does not reset', f: sub('    this._ctl.reset();\n    this._resetUi();', '    this._resetUi();') },
  { id: 'AC3-no-pagehide', ac: 'AC3', note: 'no reset on pagehide', f: sub("window.addEventListener('pagehide', this._onPageHide);", '') },
  { id: 'AC3-resize-resets-always', ac: 'AC3', note: 'any resize resets', f: sub('if (r && r.width === 0 && r.height === 0) this._ctl.reset();', 'if (r) this._ctl.reset();') },
  { id: 'AC3-no-hidden-observer', ac: 'AC3', note: 'the element is not observed for being hidden', f: sub('this._ro.observe(this);', '') },
  // ---- AC4 independence
  { id: 'AC4-shared-mode', ac: 'AC4', note: 'the mode is shared by every controller',
    f: chain(sub('let mode = DEFAULT_MODE;', 'const S = createModeController.s || (createModeController.s = { m: DEFAULT_MODE });'), sub('      return mode;', '      return S.m;'),
      sub('      mode = next;\n      if (typeof onChange', '      S.m = next;\n      if (typeof onChange'), sub('      if (!MODES.includes(next) || next === mode) return false;', '      if (!MODES.includes(next) || next === S.m) return false;'),
      sub('      if (mode === DEFAULT_MODE) return false;\n      mode = DEFAULT_MODE;\n      if (typeof onChange === \'function\') onChange(mode,', '      if (S.m === DEFAULT_MODE) return false;\n      S.m = DEFAULT_MODE;\n      if (typeof onChange === \'function\') onChange(S.m,'),
      sub("if (typeof onChange === 'function') onChange(mode, 'set');", "if (typeof onChange === 'function') onChange(S.m, 'set');")) },
  // ---- AC5 zero calls, no storage, no hass reads (8 mutants)
  { id: 'AC5-switch-calls-service', ac: 'AC5', note: 'the switch calls hass.callService', f: sub("on(b, 'click', () => this._ctl.set(mode));", "on(b, 'click', () => { this._ctl.set(mode); if (this._hass) this._hass.callService('x', 'y'); });") },
  { id: 'AC5-mode-in-localstorage', ac: 'AC5', note: 'the mode is stored in localStorage', f: sub('      mode = next;\n      if (typeof onChange', "      mode = next;\n      localStorage.setItem('m', next);\n      if (typeof onChange") },
  { id: 'AC5-copy-fetches', ac: 'AC5', note: 'copy phones home with fetch', f: sub("    const say = (m) => {\n      if (this._geek) this._geek.say(m);\n    };", "    fetch('x');\n    const say = (m) => {\n      if (this._geek) this._geek.say(m);\n    };") },
  { id: 'AC5-export-opens-window', ac: 'AC5', note: 'export uses window.open', f: sub('    a.click();', '    window.open(url);') },
  { id: 'AC5-reads-other-hass-property', ac: 'AC5', note: 'reads hass.user', f: sub('    const states = this._statesObj();\n    const now = this._now();', '    const states = this._statesObj();\n    void (this._hass && this._hass.user);\n    const now = this._now();') },
  { id: 'AC5-search-in-sessionstorage', ac: 'AC5', note: 'the search text is remembered in sessionStorage', f: sub('      this.q = ui.search.value;\n      this.page = 0;', "      this.q = ui.search.value;\n      sessionStorage.setItem('q', this.q);\n      this.page = 0;") },
  { id: 'AC5-mode-change-calls-ws', ac: 'AC5', note: 'a mode change calls hass.callWS', f: sub('    const mode = this._ctl.mode;\n    ui.shell.setAttribute', "    const mode = this._ctl.mode;\n    if (this._hass) this._hass.callWS({ type: 'x' });\n    ui.shell.setAttribute") },
  { id: 'AC5-open-pushes-history', ac: 'AC5', note: 'opening an entity pushes browser history', f: sub('    if (typeof CustomEvent !== \'function\') return;', "    window.history.pushState({}, '', '/x');\n    if (typeof CustomEvent !== 'function') return;") },
  // ---- AC6 the alert strip (8 mutants)
  { id: 'AC6-strip-hidden-in-geek', ac: 'AC6', note: 'Geek Mode hides the strip', f: sub("    ui.geekBody.hidden = mode !== 'geek';", "    ui.geekBody.hidden = mode !== 'geek';\n    ui.strip.hidden = mode === 'geek';") },
  { id: 'AC6-strip-only-first-in-geek', ac: 'AC6', note: 'Geek Mode shows only the first alert', f: sub("    ui.geekBody.hidden = mode !== 'geek';", "    ui.geekBody.hidden = mode !== 'geek';\n    renderAlertStrip(this.ownerDocument, ui.strip, mode === 'geek' ? this._alerts.slice(0, 1) : this._alerts);") },
  { id: 'AC6-strip-inside-production-body', ac: 'AC6', note: 'the strip lives inside the Production body', f: chain(sub("[summary, prodKids]);", '[strip, summary, prodKids]);'), sub('      strip, always, prodBody, geekBody,', '      always, prodBody, geekBody,')) },
  { id: 'AC6-info-alerts-dropped', ac: 'AC6', note: 'info alerts never shown', f: sub("if (verdict[i] === 'active') out.push(", "if (verdict[i] === 'active' && a.severity !== 'info') out.push(") },
  { id: 'AC6-unknown-not-down', ac: 'AC6', note: 'unknown is not treated as not publishing', f: sub(" || input.state === 'unavailable' || input.state === 'unknown';", " || input.state === 'unavailable';") },
  { id: 'AC6-not-in-inverted', ac: 'AC6', note: 'state_not_in inverted', f: sub('return down || !when.state_not_in.includes(input.state)', 'return down || when.state_not_in.includes(input.state)') },
  { id: 'AC6-no-unverifiable', ac: 'AC6', note: 'conditions that cannot be checked vanish', f: sub("else if (verdict[i] === 'unknown' && !downActive.has(a.entity_id)) {", 'else if (false) {') },
  { id: 'AC6-action-text-dropped', ac: 'AC6', note: 'the what-to-do line is empty', f: sub('`What to do: ${a.action}`)]);', "'')]);") },
  { id: 'AC6-order-reversed', ac: 'AC6', note: 'info before critical', f: sub('SEVERITY_RANK[x.severity] - SEVERITY_RANK[y.severity] ||', 'SEVERITY_RANK[y.severity] - SEVERITY_RANK[x.severity] ||') },
  // ---- AC7 one snapshot
  { id: 'AC7-geek-not-updated', ac: 'AC7', note: 'Geek rows do not follow hass', f: sub('    if (this._geek) this._geek.update(this._snap);\n  }\n\n  // ---- the only three things', '  }\n\n  // ---- the only three things') },
  { id: 'AC7-children-not-fed', ac: 'AC7', note: 'children never get the new hass', f: sub('    for (const k of this._kids) k.hass = hass;\n', '') },
  // ---- AC8 coverage
  { id: 'AC8-no-discovery', ac: 'AC8', note: 'discovery switched off', f: sub('if (cat.discover.prefixes.length) {', 'if (false) {') },
  { id: 'AC8-discovers-outside-prefix', ac: 'AC8', note: 'every entity of the domain is discovered', f: sub('if (id.startsWith(p)) {', "if (id.startsWith(p.split('.')[0] + '.')) {") },
  { id: 'AC8-absent-attribute-faked', ac: 'AC8', note: 'a declared absent attribute is shown as present', f: sub('    const present = hasOwn(red, top);', '    const present = hasOwn(red, top) || true;') },
  // ---- AC9 honesty
  { id: 'AC9-never-stale', ac: 'AC9', note: 'staleness never detected', f: sub('const stale = limit !== null && ageS !== null && ageS > limit;', 'const stale = false;') },
  { id: 'AC9-missing-is-unknown', ac: 'AC9', note: 'a missing entity is called unknown', f: sub("if (!isObj(state)) return { status: 'NOT_MEASURED', flags: ['NOT_MEASURED']", "if (!isObj(state)) return { status: 'UNKNOWN', flags: ['UNKNOWN']") },
  { id: 'AC9-unavailable-shows-value', ac: 'AC9', note: 'an unavailable row still shows a value', f: sub("else if (cls.status === 'UNAVAILABLE') stateText = 'Unavailable';", "else if (cls.status === 'UNAVAILABLE') stateText = parts.stateStr;") },
  { id: 'AC9-stale-called-live', ac: 'AC9', note: 'a stale value is also flagged live', f: sub('  return done(flags[0], flags);', "  return done('LIVE', ['LIVE', ...flags]);") },
  { id: 'AC9-chip-without-icon', ac: 'AC9', note: 'a status chip is colour and words only', f: sub('[icon(doc, STATUS_ICON[status]), mk(doc, \'span\', null, STATUS_WORD[status])]', "[mk(doc, 'span', null, STATUS_WORD[status])]") },
  { id: 'AC9-no-timestamp-is-live', ac: 'AC9', note: 'a source with a freshness rule but no timestamp is live', f: sub('(limit !== null && ageS === null) || ', '') },
  // ---- AC10 redaction (12 mutants)
  { id: 'AC10-token-key-not-secret', ac: 'AC10', note: 'the word token is not a secret key', f: sub("new Set(['token', 'tokens', ", "new Set(['tokens', ") },
  { id: 'AC10-no-jwt-rule', ac: 'AC10', note: 'JWT-like strings pass', f: sub("['jwt', 'eyJ',", "['jwt', 'zzzz',") },
  { id: 'AC10-no-hex-rule', ac: 'AC10', note: 'long hex blobs pass', f: sub("if (!digestOk && RE_HEX.test(s)) return 'long hex value';", '') },
  { id: 'AC10-search-index-raw', ac: 'AC10', note: 'the search index is built from raw attributes', f: sub('flattenForSearch(red, bits,', 'flattenForSearch(attrsRaw, bits,') },
  { id: 'AC10-list-items-not-redacted', ac: 'AC10', note: 'list items are copied unredacted', f: sub('out.push(redactNode(v[i], key, ctx, depth + 1));', 'out.push(v[i]);') },
  { id: 'AC10-key-names-not-redacted', ac: 'AC10', note: 'secret-looking key names pass', f: sub('else if (valueReason(k.length > 200 ? k.slice(0, 200) : k, false) !== null) {', 'else if (false) {') },
  { id: 'AC10-export-not-reredacted', ac: 'AC10', note: 'the export skips its final redaction pass', f: sub('const items = redactValue((Array.isArray(rows) ? rows : []).map(exportRow));', 'const items = (Array.isArray(rows) ? rows : []).map(exportRow);') },
  { id: 'AC10-state-not-redacted', ac: 'AC10', note: 'a secret-looking state is shown', f: sub('const stateRed = redactValue(stateStr, opts);', 'const stateRed = stateStr;') },
  { id: 'AC10-no-userinfo-rule', ac: 'AC10', note: 'URLs with credentials pass', f: sub("['url credentials', '@',", "['url credentials', 'zzzz',") },
  { id: 'AC10-no-ipv4-rule', ac: 'AC10', note: 'IP addresses pass', f: sub("['IPv4 address', '.',", "['IPv4 address', 'zzzz',") },
  { id: 'AC10-extra-patterns-ignored', ac: 'AC10', note: 'the catalogue extra key patterns are ignored', f: sub('  for (const re of extra) if (re.test(k)) return true;', '') },
  { id: 'AC10-privacy-keys-ignored', ac: 'AC10', note: 'latitude, longitude, address and friends pass', f: sub('if (SECRET_TOKENS.has(tokens[i]) || PRIVATE_TOKENS.has(tokens[i])) return true;', 'if (SECRET_TOKENS.has(tokens[i])) return true;') },
  { id: 'AC10-discovered-id-not-redacted', ac: 'AC10', note: 'a discovered entity id that looks secret is shown', f: sub("const shown = redactString(id, 'note');", 'const shown = id;') },
  // ---- AC11 search and filters
  { id: 'AC11-terms-or', ac: 'AC11', note: 'search terms are OR-ed', f: sub('terms.every((t) => r.searchText.includes(t))', 'terms.some((t) => r.searchText.includes(t))') },
  { id: 'AC11-problems-ignored', ac: 'AC11', note: 'the problems filter does nothing', f: sub('(!f.problems || r.problem)', 'true') },
  // ---- AC12 performance and caps
  { id: 'AC12-rebuild-every-row', ac: 'AC12', note: 'no row reuse', f: sub('if (hit && hit.sig === sig) {', 'if (false) {') },
  { id: 'AC12-no-windowing', ac: 'AC12', note: 'all rows are rendered', f: sub('const win = windowRows(visible, this.page, this.o.pageSize);', 'const win = { rows: visible, page: 0, pageCount: 1, total: visible.length, start: 0, end: visible.length };') },
  { id: 'AC12-no-dict-cap', ac: 'AC12', note: 'a dict with thousands of keys is kept whole', f: sub('if (i >= LIMITS.dictKeys) {', 'if (false) {') },
  { id: 'AC12-no-list-cap', ac: 'AC12', note: 'a list with thousands of items is kept whole', f: sub('const n = Math.min(v.length, LIMITS.listItems);', 'const n = v.length;') },
  { id: 'AC12-no-parts-cache', ac: 'AC12', note: 'every snapshot recomputes every row', f: sub('if (hit && hit.cat === cat && hit.ref === ref) return hit;', '') },
  // ---- AC13 inert text (8 mutants)
  { id: 'AC13-innerhtml-notice', ac: 'AC13', note: 'a notice is built with innerHTML', f: sub("return mk(doc, 'div', { class: 'notice', [flag]: '', role: 'note' }, cleanText(text, 400));", "const n = mk(doc, 'div', { class: 'notice', [flag]: '', role: 'note' });\n    n.innerHTML = text;\n    return n;") },
  { id: 'AC13-attribute-name-from-data', ac: 'AC13', note: 'an attribute name comes from data', f: sub("class: 'attr', 'data-attribute-path': a.path,", "class: 'attr', [a.name]: 'x', 'data-attribute-path': a.path,") },
  { id: 'AC13-tag-from-data', ac: 'AC13', note: 'an element name comes from data', f: sub("mk(doc, 'span', { class: 'attr-name' }, a.depth", 'mk(doc, a.name, { class: \'attr-name\' }, a.depth') },
  { id: 'AC13-controls-not-escaped', ac: 'AC13', note: 'control and bidi characters are shown raw', f: sub('s = s.replace(CTRL, (c) =>', 's = s.replace(/zzzzz/g, (c) =>') },
  { id: 'AC13-no-truncation', ac: 'AC13', note: 'long text is not truncated', f: sub('  if (s.length > max) {', '  if (false) {') },
  { id: 'AC13-event-handler-attribute', ac: 'AC13', note: 'an onclick attribute is set from data', f: sub("'data-priority': row.priority, 'data-source-id': row.id,", "'data-priority': row.priority, onclick: row.stateText, 'data-source-id': row.id,") },
  { id: 'AC13-img-element', ac: 'AC13', note: 'an image element is created', f: sub("const chipNode = (doc, status) => mk(doc, 'span', { class: 'chip', 'data-status-chip': status }", "const chipNode = (doc, status) => mk(doc, 'img', { class: 'chip', 'data-status-chip': status }") },
  { id: 'AC13-style-from-data', ac: 'AC13', note: 'an inline style value comes from data', f: sub("ringEl.style.setProperty('--ecco-p', String(ring.pct));", "ringEl.style.setProperty('--ecco-p', r.title);") },
  // ---- AC14 accessibility
  { id: 'AC14-radio-state-not-updated', ac: 'AC14', note: 'aria-checked is never set', f: sub("ui.opts[m].setAttribute('aria-checked', m === mode ? 'true' : 'false');", "ui.opts[m].setAttribute('aria-checked', 'false');") },
  { id: 'AC14-no-arrow-right', ac: 'AC14', note: 'the right arrow does nothing', f: sub("if (ev.key === 'ArrowRight' || ev.key === 'ArrowDown')", "if (ev.key === 'ArrowDown')") },
  { id: 'AC14-motion-not-reduced', ac: 'AC14', note: 'reduced motion does not stop animation', f: sub('animation: none !important;transition: none !important;', 'animation: none;transition: none;') },
  { id: 'AC14-small-targets', ac: 'AC14', note: 'targets shrink below 44 px', f: sub('min-height:44px', 'min-height:30px', true) },
  { id: 'AC14-button-without-type', ac: 'AC14', note: 'the radio button has no type', f: sub("mk(doc, 'button', { type: 'button', role: 'radio',", "mk(doc, 'button', { role: 'radio',") },
  // ---- AC16 authority and fail closed
  { id: 'AC16-guard-off', ac: 'AC16', note: 'the child guard is switched off', f: sub('const verdict = guard ? validateChildCards(configs) :', 'const verdict = false ? validateChildCards(configs) :') },
  { id: 'AC16-toggle-allowed', ac: 'AC16', note: 'toggle counts as a safe action', f: sub("const SAFE_ACTIONS = Object.freeze(['none', 'more-info', 'navigate']);", "const SAFE_ACTIONS = Object.freeze(['none', 'more-info', 'navigate', 'toggle']);") },
  { id: 'AC16-config-cloned', ac: 'AC16', note: 'the child gets a copy, not the configuration', f: sub('el.setConfig(cfg);', 'el.setConfig({ ...cfg });') },
  { id: 'AC16-production-not-hidden-in-geek', ac: 'AC16', note: 'the Production body stays visible in Geek Mode', f: sub("ui.prodBody.hidden = mode !== 'production';", 'ui.prodBody.hidden = false;') },
  { id: 'AC16-invalid-catalogue-shows-inventory', ac: 'AC16', note: 'an invalid catalogue still builds the inventory', f: sub('catalogueOk: this._cat.ok,', 'catalogueOk: true,') },
  { id: 'AC16-shell-alerts-dropped', ac: 'AC16', note: 'the shell own alerts are not shown', f: sub('this._alerts = [...deriveAlerts(this._snap, cat), ...this._shellAlerts];', 'this._alerts = [...deriveAlerts(this._snap, cat)];') },
  { id: 'AC16-schema-not-checked', ac: 'AC16', note: 'an unknown schema is accepted', f: sub('const schemaOk = input.schema === CATALOGUE_SCHEMA;', 'const schemaOk = true;') },
  { id: 'AC16-nested-cards-not-walked', ac: 'AC16', note: 'the guard does not look inside nested cards', f: sub("    if (v !== null && typeof v === 'object') walkCard(v, `${path}.${k}`, bad, seen, depth + 1);", '') },
];

const MIN = { AC5: 6, AC6: 6, AC10: 6, AC13: 6 };

function runSuites(file) {
  return new Promise((resolve) => {
    // NODE_TEST_CONTEXT is set by the outer test runner; inherited, it would turn the nested `node --test` into a silent no-op.
    const env = { ...process.env, ECCO_MODE_SHELL_PATH: file, ECCO_SKIP_MUTATIONS: '1' };
    delete env.NODE_TEST_CONTEXT;
    const child = spawn(process.execPath, ['--test', ...SUITES], { env, stdio: ['ignore', 'pipe', 'pipe'] });
    let out = '';
    child.stdout.on('data', (d) => { out += d; });
    child.stderr.on('data', (d) => { out += d; });
    child.on('close', (code) => resolve({ code, out }));
  });
}

async function pool(items, size, fn) {
  const results = new Array(items.length);
  let next = 0;
  await Promise.all(Array.from({ length: size }, async () => {
    while (next < items.length) {
      const i = next;
      next += 1;
      results[i] = await fn(items[i]);
    }
  }));
  return results;
}

if (nested) {
  test('mutation runner: skipped inside a mutant run (no recursion)', { skip: true }, () => {});
} else {
  const dir = mkdtempSync(path.join(tmpdir(), 'ecco-mode-shell-mut-'));
  const original = readFileSync(REAL, 'utf8');
  const prepared = MUTANTS.map((m) => {
    try {
      const mutated = m.f(original);
      assert.notEqual(mutated, original, 'the mutation changed nothing');
      const file = path.join(dir, `${m.id}.mjs`);
      writeFileSync(file, mutated);
      return { ...m, file, error: null };
    } catch (e) {
      return { ...m, file: null, error: e.message };
    }
  });
  const baseFile = path.join(dir, 'baseline.mjs');
  writeFileSync(baseFile, original);
  const baseline = await runSuites(baseFile);
  const results = await pool(prepared, 6, async (m) => (m.file ? { ...m, run: await runSuites(m.file) } : { ...m, run: null }));
  rmSync(dir, { recursive: true, force: true });

  test('mutation baseline: the unmutated copy passes the suites it is run against (the harness works)', () => {
    assert.equal(baseline.code, 0, baseline.out.slice(-2000));
  });

  for (const m of results) {
    test(`mutant ${m.id} (${m.ac}): ${m.note}: is killed`, () => {
      assert.equal(m.error, null, m.error);
      assert.notEqual(m.run.code, 0, `SURVIVED: no test failed with this break`);
    });
  }

  test('mutation coverage: each case that needs a mutation proof has enough mutants, and all were killed', () => {
    const per = {};
    for (const m of results) per[m.ac] = (per[m.ac] || 0) + 1;
    for (const [ac, n] of Object.entries(MIN)) assert.ok((per[ac] || 0) >= n, `${ac} has ${per[ac] || 0} mutants, needs ${n}`);
    const survivors = results.filter((m) => m.error !== null || m.run.code === 0).map((m) => m.id);
    assert.deepEqual(survivors, []);
    console.log(`mutation score: ${results.length - survivors.length}/${results.length} killed; per case ${JSON.stringify(per)}`);
  });
}
