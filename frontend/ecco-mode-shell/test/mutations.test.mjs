// Mutation proof: every acceptance case that needs one is shown to FAIL without its behaviour. Each mutant is a small,
// deliberate break of the card (written to a scratch copy in the OS temp folder, never in the repository); the other
// test files are run against it with ECCO_MODE_SHELL_PATH pointing at the copy, and the mutant is KILLED when that run
// fails. A mutant whose target text is not found exactly once is itself a failure (the table would otherwise rot silently).
// AC5, AC6, AC10 and AC13 have at least six mutants each (this file asserts it); the others have at least one.
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { cardDir } from './helpers.mjs';
import { findBrowser } from '../preview/check-strip.mjs';

const nested = process.env.ECCO_MODE_SHELL_PATH !== undefined || process.env.ECCO_SKIP_MUTATIONS === '1';
const REAL = path.join(cardDir, 'ecco-mode-shell.js');
// review round 9: async.test.mjs (the pin of the places where the card may defer work) and cache.test.mjs (warm caches against a cold read) are in the list
const SUITES = ['core.test.mjs', 'element.test.mjs', 'static.test.mjs', 'coverage.test.mjs', 'real-catalogue.test.mjs', 'scan.test.mjs', 'budget.test.mjs', 'async.test.mjs', 'cache.test.mjs'].map((f) => path.join(cardDir, 'test', f));
// review round 7: the timing tests take several seconds, so only the mutants about speed (`perf: true`) and the baseline are given them
const PERF_SUITE = path.join(cardDir, 'test', 'perf.test.mjs');
// review round 8: the differential gate (test/differential.test.mjs) is heavy too, so it is given only to the mutants about the rules (`diff: true`) and to the baseline
const DIFF_SUITE = path.join(cardDir, 'test', 'differential.test.mjs');
const extraSuites = (m) => [...(m.perf ? [PERF_SUITE] : []), ...(m.diff ? [DIFF_SUITE] : [])];

/** sub(find, replace[, all]): replace the one occurrence of `find` (or every occurrence with all = true). */
const sub = (find, replace, all = false) => (s) => {
  const n = s.split(find).length - 1;
  if (n === 0 || (n > 1 && !all)) throw new Error(`mutation target found ${n} times: ${find.slice(0, 80)}`);
  return s.split(find).join(replace);
};
const chain = (...fs) => (s) => fs.reduce((acc, f) => f(acc), s);
const GEEK_LINE = "    ui.geekBody.hidden = mode !== 'geek';";
const SCAN_LINE = '  if (valueReason(t, digestOk, digestKey) !== null) return WITHHELD;';
// review round 9
const gl9 = (code) => sub(GEEK_LINE, `${GEEK_LINE}\n${code}`);
const IS_GEEK9 = "this._ctl.mode === 'geek' && this._ui";
const RENDER_END9 = '  strip.replaceChildren(...kids);\n}';
// review round 10: the anchors of the clock, continuation, count and key-count mutants
const BUILT10 = '        this._geek.build();';
const RENDER10 = '    renderAlertStrip(this.ownerDocument, ui.strip, this._alerts);';
const SAMEW10 = '    if (watch === null || Object.keys(states).length !== this._keyCount) return false;';
const NOTLIVE10 = "    if (r.status !== 'LIVE') counts.notLive += 1;";

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
  { id: 'AC10-export-not-reredacted', ac: 'AC10', note: 'the export skips its final redaction pass', f: sub('const items = redactValue((Array.isArray(rows) ? rows : []).map(exportRow), { eachItem: true });', 'const items = (Array.isArray(rows) ? rows : []).map(exportRow);') },
  { id: 'AC10-state-not-redacted', ac: 'AC10', note: 'a secret-looking state is shown', f: sub('const stateRed = redactValue(stateStr, opts);', 'const stateRed = stateStr;') },
  { id: 'AC10-no-userinfo-rule', ac: 'AC10', note: 'URLs with credentials pass', f: sub("['url credentials', '@',", "['url credentials', 'zzzz',") },
  { id: 'AC10-no-ipv4-rule', ac: 'AC10', note: 'IP addresses pass', f: sub("['IPv4 address', '.',", "['IPv4 address', 'zzzz',") },
  { id: 'AC10-extra-patterns-ignored', ac: 'AC10', note: 'the catalogue extra key patterns are ignored', f: sub("  return keyHasFragment(fold(String(key)), extra) || keyHasFragment(tokens.join('_'), extra);", '  return false;') },
  { id: 'AC10-privacy-keys-ignored', ac: 'AC10', note: 'latitude, longitude, address and friends pass', f: sub('if (SECRET_TOKENS.has(tokens[i]) || PRIVATE_TOKENS.has(tokens[i])) return true;', 'if (SECRET_TOKENS.has(tokens[i])) return true;') },
  { id: 'AC10-discovered-id-not-redacted', ac: 'AC10', note: 'a discovered entity id that looks secret is shown', f: sub("? WITHHELD : redactString(job.id, 'note');", '? WITHHELD : job.id;') },
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
  { id: 'AC16-guard-off', ac: 'AC16', note: 'the child guard is switched off', f: sub('const verdict = guard ? validateChildCards(configs, { allowCustom: this._config.allowCustom }) :', 'const verdict = false ? validateChildCards(configs, { allowCustom: this._config.allowCustom }) :') },
  { id: 'AC16-toggle-allowed', ac: 'AC16', note: 'toggle counts as a safe action', f: sub("const SAFE_ACTIONS = Object.freeze(['none', 'more-info', 'navigate']);", "const SAFE_ACTIONS = Object.freeze(['none', 'more-info', 'navigate', 'toggle']);") },
  { id: 'AC16-config-cloned', ac: 'AC16', note: 'the child gets a copy, not the configuration', f: sub('el.setConfig(cfg);', 'el.setConfig({ ...cfg });') },
  { id: 'AC16-production-not-hidden-in-geek', ac: 'AC16', note: 'the Production body stays visible in Geek Mode', f: sub("ui.prodBody.hidden = mode !== 'production';", 'ui.prodBody.hidden = false;') },
  { id: 'AC16-invalid-catalogue-shows-inventory', ac: 'AC16', note: 'an invalid catalogue still builds the inventory', f: sub('catalogueOk: this._cat.ok,', 'catalogueOk: true,') },
  { id: 'AC16-shell-alerts-dropped', ac: 'AC16', note: 'the shell own alerts are not shown', f: sub('this._alerts = [...deriveAlerts(this._snap, cat), ...this._shellAlerts];', 'this._alerts = [...deriveAlerts(this._snap, cat)];') },
  { id: 'AC16-schema-not-checked', ac: 'AC16', note: 'an unknown schema is accepted', f: sub('const schemaOk = input.schema === CATALOGUE_SCHEMA;', 'const schemaOk = true;') },
  // ---- integration with the real catalogue (the card and the data side must agree: real-catalogue.test.mjs)
  { id: 'AC6-bool-in-list-rejected', ac: 'AC6', note: 'an alert whose in-list holds a boolean is dropped as invalid (the critical applies_nothing alert)', f: sub("w.in.every((x) => isStr(x) || typeof x === 'boolean')", 'w.in.every(isStr)') },
  { id: 'AC6-listed-down-state-silent', ac: 'AC6', note: 'a listed unknown state does not fire its own alert', f: sub("  if (when.state_in && input.present && when.state_in.includes(input.state)) return 'active';\n", '') },
  { id: 'AC6-unavailable-fires-on-unknown', ac: 'AC6', note: 'an unknown state raises the critical unavailable alert', f: sub("return !input.present || input.state === 'unavailable' ? 'active' : input.state === 'unknown' ? 'unknown' : 'clear';", "return down ? 'active' : 'clear';") },
  { id: 'AC6-unavailable-ignores-missing', ac: 'AC6', note: 'a missing declared entity does not fire the unavailable alert', f: sub("return !input.present || input.state === 'unavailable' ? 'active' :", "return input.present && input.state === 'unavailable' ? 'active' :") },
  { id: 'AC6-redundant-lines-kept', ac: 'AC6', note: 'a listed unknown state does not silence the cannot-check lines for that entity', f: sub(" || (a.when.state_in && (input.state === 'unavailable' || input.state === 'unknown')))) downActive.add(a.entity_id);", ')) downActive.add(a.entity_id);') },
  { id: 'AC8-rows-capped-low', ac: 'AC8', note: 'only twenty attribute rows are listed for an entity', f: sub('attrsPerRow: 200,', 'attrsPerRow: 20,') },
  { id: 'AC8-declared-subrows-dropped', ac: 'AC8', note: 'declared first-level paths of a present dict are not listed', f: sub('      subs.push(attrRow(a.name, rest, top, rest.split(\'.\').length, a, has, has ? value[rest] : undefined));', '') },
  { id: 'AC10-extra-patterns-not-prepared', ac: 'AC10', note: 'the catalogue extra key patterns never reach the redactor', f: sub('const opts = { extraKeyPatterns: cat.extraPatterns, scan: newScan(), work };', 'const opts = { extraKeyPatterns: [], scan: newScan(), work };') },
  { id: 'AC16-nested-cards-not-walked', ac: 'AC16', note: 'the guard does not look inside nested cards', f: sub("    if (v !== null && typeof v === 'object') walkCard(v, `${path}.${k}`, bad, seen, depth + 1);", '') },
  // ---- review round 1: each fix is shown to be needed by a mutant that undoes it
  { id: 'AC16-open-row-any-domain', ac: 'AC16', note: 'the row offers Open in Home Assistant for every domain (a writable domain dialog is an extra write path)', f: sub('      if (canOpenMoreInfo(row.entity_id)) {', '      if (true) {') },
  { id: 'AC16-open-dispatch-any-domain', ac: 'AC16', note: 'the dispatch itself no longer checks the domain', f: sub('    if (!canOpenMoreInfo(entityId)) return;\n', '') },
  { id: 'AC16-open-domains-widened', ac: 'AC16', note: 'a writable domain is added to the list of domains whose dialog may be opened', f: sub("Object.freeze(['sensor', 'binary_sensor', 'event']);", "Object.freeze(['sensor', 'binary_sensor', 'event', 'input_boolean']);") },
  { id: 'AC16-open-id-unanchored', ac: 'AC16', note: 'the domain is read from the front of any text, so a malformed id passes', f: sub('  return isStr(entityId) && MORE_INFO_ID.test(entityId);', "  return isStr(entityId) && MORE_INFO_DOMAINS.includes(entityId.split('.')[0]);") },
  { id: 'AC6-css-hides-strip-in-geek', ac: 'AC6', note: 'the stylesheet hides the alert strip in Geek Mode (the reviewer mutant R10)', f: sub('.alert-head{font-weight:700}', '.alert-head{font-weight:700}\n.shell[data-mode="geek"] .alerts{display:none}') },
  { id: 'AC6-css-strip-opacity-zero', ac: 'AC6', note: 'the stylesheet makes the strip transparent', f: sub('.alert-head{font-weight:700}', '.alert-head{font-weight:700}\n.alerts{opacity:0}') },
  { id: 'AC6-css-strip-hidden-by-body-selector', ac: 'AC6', note: 'the stylesheet hides the strip by a sibling selector on the Geek body', f: sub('.alert-head{font-weight:700}', '.alert-head{font-weight:700}\n[data-ecco-body="geek"] ~ .alerts{visibility:hidden}') },
  { id: 'AC6-css-mode-selector-added', ac: 'AC6', note: 'a new mode-dependent selector appears in the stylesheet', f: sub('.opt[aria-checked="true"]{color:#fff}', '.opt[aria-checked="true"]{color:#fff}\n.shell[data-mode="geek"] .summary{display:none}') },
  { id: 'AC6-css-strip-collapsed-in-container', ac: 'AC6', note: 'a container query collapses the strip', f: sub('.alert-head{font-weight:700}', '.alert-head{font-weight:700}\n@container (max-width:560px){.alerts{max-height:0;overflow:hidden}}') },
  // ---- review round 2: the stylesheet cannot shift or clip the strip either (the reviewer mutant R2-16 and the ways around it)
  { id: 'AC6-css-strip-shifted-by-last-region', ac: 'AC6', note: 'a selector that picks the Geek body (the last region) out by position shifts the strip off screen in Geek Mode only (the reviewer mutant R2-16)', f: sub('.alert-head{font-weight:700}', '.alert-head{font-weight:700}\n.shell:has(> .region:last-child:not([hidden])) .alerts{margin-left:-200vw}') },
  { id: 'AC6-css-strip-own-rule-margin', ac: 'AC6', note: 'the strip rule itself gets a huge negative margin', f: sub('.alerts{display:grid;gap:8px;min-width:0}', '.alerts{display:grid;gap:8px;min-width:0;margin-left:-200vw}') },
  { id: 'AC6-css-strip-offset-positioned', ac: 'AC6', note: 'the strip is positioned and moved off screen with an offset', f: sub('.alert-head{font-weight:700}', '.alert-head{font-weight:700}\n.alerts{position:relative;left:-30px}') },
  { id: 'AC6-css-children-shifted-by-universal-rule', ac: 'AC6', note: 'a rule on every child of the shell (which includes the strip) shifts them off screen', f: sub('.alert-head{font-weight:700}', '.alert-head{font-weight:700}\n.shell>*{margin-left:-200vw}') },
  { id: 'AC6-css-strip-clipped-to-sliver', ac: 'AC6', note: 'the strip is clipped to a few pixels of height', f: sub('.alert-head{font-weight:700}', '.alert-head{font-weight:700}\n.alerts{height:4px;overflow:hidden}') },
  { id: 'AC6-css-strip-behind-background', ac: 'AC6', note: 'the strip gets a negative z-index', f: sub('.alert-head{font-weight:700}', '.alert-head{font-weight:700}\n.alerts{position:relative;z-index:-1}') },
  { id: 'AC6-css-new-strip-selector', ac: 'AC6', note: 'a new selector that names the strip appears (harmless declarations, still a decision)', f: sub('.alert-head{font-weight:700}', '.alert-head{font-weight:700}\n.shell .alerts{gap:2px}') },
  { id: 'AC6-css-positional-selector', ac: 'AC6', note: 'a rule picks the last child of the shell by position', f: sub('.alert-head{font-weight:700}', '.alert-head{font-weight:700}\n.shell>:last-child{border:0}') },
  { id: 'AC3-setconfig-no-reset', ac: 'AC3', note: 'setConfig on the same element keeps Geek Mode', f: sub('    this._ctl.reset();\n    const cfg = validateConfig(config);', '    const cfg = validateConfig(config);') },
  { id: 'AC3-setconfig-forces-geek', ac: 'AC3', note: 'setConfig switches to Geek Mode', f: sub('    this._ctl.reset();\n    const cfg = validateConfig(config);', "    this._ctl.set('geek');\n    const cfg = validateConfig(config);") },
  { id: 'AC6-not-in-coerced', ac: 'AC6', note: 'not_in compares as text, so the text "true" counts as the boolean true', f: sub('when.not_in.some((x) => x === v)', 'when.not_in.some((x) => String(x) === String(v))') },
  { id: 'AC6-attribute-not-in-inverted', ac: 'AC6', note: 'not_in fires when the value IS listed', f: sub("if (when.not_in) return when.not_in.some((x) => x === v) ? 'clear' : 'active';", "if (when.not_in) return when.not_in.some((x) => x === v) ? 'active' : 'clear';") },
  { id: 'AC6-state-outside-inverted', ac: 'AC6', note: 'state_outside fires for a listed state', f: sub("return when.state_outside.includes(input.state) ? 'clear' : 'active';", "return when.state_outside.includes(input.state) ? 'active' : 'clear';") },
  { id: 'AC6-state-outside-fires-when-down', ac: 'AC6', note: 'state_outside also fires for an unavailable or unknown state', f: sub("  if (down) return 'unknown';\n  if (when.state_in)", "  if (down && !when.state_outside) return 'unknown';\n  if (when.state_in)") },
  { id: 'AC6-in-and-not-in-both-accepted', ac: 'AC6', note: 'an alert with both in and not_in is accepted', f: sub("  if (isStr(w.attribute) && w.attribute !== '' && hasOwn(w, 'in') && hasOwn(w, 'not_in')) return null;\n", '') },
  { id: 'AC6-not-in-empty-accepted', ac: 'AC6', note: 'an empty not_in list is accepted (it would fire for everything)', f: sub('Array.isArray(w.not_in) && w.not_in.length > 0 &&', 'Array.isArray(w.not_in) &&') },
  { id: 'AC6-state-outside-empty-accepted', ac: 'AC6', note: 'an empty state_outside list is accepted', f: sub('Array.isArray(w.state_outside) && w.state_outside.length > 0 &&', 'Array.isArray(w.state_outside) &&') },
  { id: 'AC16-allowlist-off', ac: 'AC16', note: 'any built-in card type may sit in a Geek-visible region', f: sub('  } else if (!ALLOWED_CARD_TYPES.has(type)) bad(', '  } else if (false) bad(') },
  { id: 'AC16-custom-any', ac: 'AC16', note: 'any custom card may sit in a Geek-visible region', f: sub('    if (!custom.has(type)) bad(', '    if (false) bad(') },
  { id: 'AC16-containers-not-checked', ac: 'AC16', note: 'the cards inside a stack, grid or conditional are not checked against the allowlist', f: sub('  if (CONTAINER_TYPES.has(type)) {', '  if (false) {') },
  { id: 'AC16-header-footer-not-checked', ac: 'AC16', note: 'a card header or footer is not checked', f: sub('    if (isObj(hf) && !ALLOWED_HEADER_FOOTER.has(hf.type)) bad(', '    if (false) bad(') },
  { id: 'AC16-heading-badge-unchecked', ac: 'AC16', note: 'a heading badge on a writable entity needs no explicit action', f: sub("  if (type === 'heading' && Array.isArray(card.badges)) {", '  if (false) {') },
  { id: 'AC16-allow-custom-ignored', ac: 'AC16', note: 'the dashboard author cannot name a custom card', f: sub('  for (const name of named) if (isStr(name) && CUSTOM_CARD_NAME.test(name)) custom.add(name);\n', '') },
  { id: 'AC16-custom-name-unchecked', ac: 'AC16', note: 'allow_custom_cards accepts any text', f: sub('if (isStr(name) && CUSTOM_CARD_NAME.test(name)) allowCustom.push(name);', 'if (isStr(name)) allowCustom.push(name);') },
  { id: 'AC16-allow-custom-not-passed', ac: 'AC16', note: 'the shell does not hand allow_custom_cards to the guard', f: sub('validateChildCards(configs, { allowCustom: this._config.allowCustom })', 'validateChildCards(configs)') },
  { id: 'AC10-no-fold-values', ac: 'AC10', note: 'values are matched as they are (zero-width and look-alike letters hide a secret)', f: sub('  const s = fold(raw);', '  const s = raw;') },
  { id: 'AC10-no-fold-keys', ac: 'AC10', note: 'key names are matched as they are', f: sub('  return fold(String(key)).replace(', '  return String(key).replace(') },
  { id: 'AC10-invisible-not-stripped', ac: 'AC10', note: 'invisible characters are not removed before matching', f: sub("  let t = s.replace(CTRL, '');", '  let t = s;') },
  { id: 'AC10-confusables-dropped', ac: 'AC10', note: 'look-alike letters are not folded', f: sub('  for (const ch of t) out += CONFUSABLES.get(ch.codePointAt(0)) || ch;', '  out = t;') },
  { id: 'AC10-key-word-rule-dropped', ac: 'AC10', note: 'a compound key name ending in key is not secret', f: sub('  if (tokens.length >= 2 && KEY_WORDS.has(tokens[tokens.length - 1])) return true;\n', '') },
  { id: 'AC10-pin-not-secret', ac: 'AC10', note: 'a pin is not a secret key name', f: sub("'psk', 'pin', 'dsn',", "'psk', 'dsn',") },
  { id: 'AC10-credential-pair-unquoted-only', ac: 'AC10', note: 'a credential pair with a quote after the word is not recognised', f: sub(')\\b["\']?\\s*[:=]\\s*["\']?[^\\s,;"\']{3,}/i],', ')\\b\\s*[:=]\\s*[^\\s,;]{3,}/i],') },
  { id: 'AC10-labelled-coordinate-dropped', ac: 'AC10', note: 'lat 51.5 lon -0.1 is shown', f: sub("['labelled coordinate', null,", "['labelled coordinate', 'zzzz',") },
  { id: 'AC10-hemisphere-coordinate-dropped', ac: 'AC10', note: 'coordinates written with hemisphere letters are shown', f: sub("['hemisphere coordinates', null,", "['hemisphere coordinates', 'zzzz',") },
  { id: 'AC10-internal-host-dropped', ac: 'AC10', note: 'a URL with a bare internal host name is shown', f: sub("['internal host name', '://',", "['internal host name', 'zzzz',") },
  { id: 'AC9-future-not-skew', ac: 'AC9', note: 'a timestamp far in the future is read as fresh', f: sub('  const skewed = lu !== null && lu - nowMs > FUTURE_SKEW_MS;', '  const skewed = false;') },
  { id: 'AC9-age-from-last-changed', ac: 'AC9', note: 'the age is read from last_changed instead of last_updated (the reviewer mutant R40)', f: sub('parseTime(state.last_updated) !== null ? parseTime(state.last_updated) : parseTime(state.last_changed);', 'parseTime(state.last_changed);') },
  { id: 'AC9-stale-limit-zero-accepted', ac: 'AC9', note: 'a freshness limit of 0 is accepted by the validator', f: sub('isNum(s.stale_after_s) && s.stale_after_s > 0)', 'isNum(s.stale_after_s) && s.stale_after_s >= 0)') },
  { id: 'AC9-simulated-vocabulary-narrow', ac: 'AC9', note: 'only simulated and synthetic count as simulated', f: sub('const SIM_RE = /^(?:simulat|synthetic|fixture|mock|demo|sample|fake|dummy)/i;', 'const SIM_RE = /^(?:simulated|synthetic)/i;') },
  { id: 'AC11-csv-numbers-guarded', ac: 'AC11', note: 'a negative number is exported with an apostrophe', f: sub(' && !PLAIN_NUMBER.test(s)) s =', ') s =') },
  { id: 'AC12-row-value-uncapped', ac: 'AC12', note: 'the row display cap is raised to a billion characters (the reviewer mutant R22)', f: sub('  value: 300,', '  value: 1000000000,') },
  { id: 'AC12-no-row-reuse', ac: 'AC12', note: 'no built row is ever reused', f: sub('  const hit = memo.get(holder);\n', '  const hit = null;\n') },
  { id: 'AC12-row-reuse-ignores-clock', ac: 'AC12', note: 'a built row is reused whatever the clock says (ages and stale tests would freeze)', f: sub('  if (Math.abs(nowMs - hit.now) >= ROW_REUSE_MS) return false;\n', '') },
  { id: 'AC12-no-relevance-skip', ac: 'AC12', note: 'an update of an entity the view does not read rebuilds everything', f: sub('      if (now - this._lastNow < 1000 && this._sameWatched(states)) {', '      if (false) {') },
  { id: 'AC12-no-burst-limit', ac: 'AC12', note: 'every hass update of a burst rebuilds', f: sub('      if (!this._admit()) return;\n', '') },
  { id: 'AC12-flush-never-armed', ac: 'AC12', note: 'a coalesced burst is never flushed (the last values stay unseen)', f: sub("    if (this._timerMs === TICK_MS || this._timerMs === 0) this._startTimer(Math.max(20, Math.ceil(BURST_WINDOW_MS - (t - recent[0]))));\n", '') },
  { id: 'AC12-flush-timer-not-restored', ac: 'AC12', note: 'after the flush the one timer stays on the short flush interval', f: sub('    if (this._timerMs !== TICK_MS) this._startTimer(TICK_MS);\n    this._tick();', '    this._tick();') },
  { id: 'AC14-theme-not-synced-on-set', ac: 'AC14', note: 'a theme change waits for the next rebuild', f: sub('    this._syncTheme();\n    this._refresh(false);', '    this._refresh(false);') },
  // ---- review round 2: the same, for the remaining findings
  { id: 'AC12-alert-entity-not-watched', ac: 'AC12', note: 'an alert on an entity that is not a source is not watched, so its change waits for the next tick (reviewer mutant R2-36)', f: sub('    watch.add(a.entity_id);\n    const s = st[a.entity_id];', '    const s = st[a.entity_id];') },
  { id: 'AC9-row-reuse-skips-reclassification', ac: 'AC9', note: 'a reused row is not re-classified, so a row built just before stale_after_s shows Live for up to a second after it', f: sub('  return cls.status === was.status && cls.flags.length === was.flags.length && cls.flags.every((f, i) => f === was.flags[i]);', '  return true;') },
  { id: 'AC16-invalid-catalogue-keeps-sources', ac: 'AC16', note: 'an invalid catalogue still builds the rows of its valid sources, so partial coverage looks complete (reviewer mutant R2-41)', f: sub("const effective = this._cat.ok ? cat : { ...cat, sources: [], discover: { entity_prefixes: [], group: 'discovered', exclude_entity_ids: [] } };", 'const effective = cat;') },
  { id: 'AC16-invalid-catalogue-keeps-discovery', ac: 'AC16', note: 'an invalid catalogue still discovers entities by prefix', f: sub("const effective = this._cat.ok ? cat : { ...cat, sources: [], discover: { entity_prefixes: [], group: 'discovered', exclude_entity_ids: [] } };", 'const effective = this._cat.ok ? cat : { ...cat, sources: [] };') },
  { id: 'AC10-no-webhook-rule', ac: 'AC10', note: 'a webhook URL under an innocent key is shown (the id in its path is the credential)', f: sub("['webhook path', '/',", "['webhook path', 'zzzz',") },
  { id: 'AC10-webhook-services-form-dropped', ac: 'AC10', note: 'the chat services webhook path is shown', f: sub('|(?<=hooks\\.[a-z0-9.-]+)\\/services\\/[A-Za-z0-9/_-]{12,}/i],', '/i],') },
  { id: 'AC10-login-key-rule-dropped', ac: 'AC10', note: 'a key such as mqtt_user or db_login is shown', f: sub('  if (tokens.length >= 2 && LOGIN_WORDS.has(tokens[tokens.length - 1])) return true;\n', '') },
  { id: 'AC10-login-key-needs-no-qualifier', ac: 'AC10', note: 'a bare user key is withheld too (the rule needs a qualifier, as the key rule does)', f: sub('  if (tokens.length >= 2 && LOGIN_WORDS.has(tokens[tokens.length - 1])) return true;', '  if (LOGIN_WORDS.has(tokens[tokens.length - 1])) return true;') },
  // ---- review round 3: state_not_in fail-safe (R3-20) and the redaction gaps
  { id: 'AC6-not-in-down-honours-list', ac: 'AC6', note: 'state_not_in reads a down entity (unknown, unavailable) against the list instead of firing (reviewer mutant R3-20)', f: sub("if (when.state_not_in) return down || !when.state_not_in.includes(input.state) ? 'active' : 'clear';", "if (when.state_not_in) return !input.present || !when.state_not_in.includes(input.state) ? 'active' : 'clear';") },
  { id: 'AC10-pass-last-word-dropped', ac: 'AC10', note: 'a key such as wifi_pass is shown', f: sub('  if (tokens.length >= 2 && PASS_WORDS.has(tokens[tokens.length - 1])) return true;\n', '') },
  { id: 'AC10-bare-pass-withheld', ac: 'AC10', note: 'a bare pass key is withheld too (it is also a test result: the rule needs a qualifier)', f: sub('  if (tokens.length >= 2 && PASS_WORDS.has(tokens[tokens.length - 1])) return true;\n', '  if (PASS_WORDS.has(tokens[tokens.length - 1])) return true;\n') },
  { id: 'AC10-pw-token-dropped', ac: 'AC10', note: 'a key named pw is shown', f: sub("'refreshtoken', 'pw', 'wifipass', 'wifipw']);", "'refreshtoken', 'wifipass', 'wifipw']);") },
  { id: 'AC10-wifipass-token-dropped', ac: 'AC10', note: 'the compact keys wifipass and wifipw are shown', f: sub("'refreshtoken', 'pw', 'wifipass', 'wifipw']);", "'refreshtoken', 'pw']);") },
  { id: 'AC10-mac-dotted-dropped', ac: 'AC10', note: 'a MAC address in the dotted form is shown', f: sub("['MAC address (dotted)', '.',", "['MAC address (dotted)', 'zzzz',") },
  { id: 'AC10-mac-dotted-versions', ac: 'AC10', note: 'the dotted-MAC rule takes any dotted hex or digit text, so a version number is withheld', f: sub('/\\b(?=[0-9a-f.]{0,13}[a-f])[0-9a-f]{4}\\.', '/\\b[0-9a-f]{4}\\.') },
  { id: 'AC10-mac12-dropped', ac: 'AC10', note: 'a MAC address with no separators is shown', f: sub("if (!digestKey && RE_MAC12.test(s)) return 'MAC address (no separators)';", '') },
  { id: 'AC10-mac12-ignores-revision-key', ac: 'AC10', note: 'the no-separator rule also withholds a short git revision under a revision key', f: sub('if (!digestKey && RE_MAC12.test(s))', 'if (RE_MAC12.test(s))') },
  { id: 'AC10-mac12-takes-digits', ac: 'AC10', note: 'the no-separator rule takes any twelve digits, so a plain number is withheld', f: sub('const RE_MAC12 = /^\\s*(?=[0-9a-f]*[a-f])[0-9a-f]{12}\\s*$/i;', 'const RE_MAC12 = /^\\s*[0-9a-f]{12}\\s*$/i;') },
  { id: 'AC10-coordinates-need-four-decimals', ac: 'AC10', note: 'a coordinate pair with three decimals is shown', f: sub('/(?:^|[^\\d.])-?\\d{1,3}\\.\\d{3,}\\s*[,;]\\s*-?\\d{1,3}\\.\\d{3,}(?![\\d.])/', '/(?:^|[^\\d.])-?\\d{1,3}\\.\\d{4,}\\s*[,;]\\s*-?\\d{1,3}\\.\\d{4,}(?![\\d.])/') },
  { id: 'AC10-pass-pair-dropped', ac: 'AC10', note: 'a JSON pair with a pass key, or pass=value, is shown', f: sub("['pass pair', null,", "['pass pair', 'zzzz',") },
  { id: 'AC10-pass-pair-colon-prose', ac: 'AC10', note: 'the pass-pair rule also takes plain prose such as pass: true', f: chain(sub('|(?<![a-z0-9])(?:pass|pw)=', '|(?<![a-z0-9])(?:pass|pw)\\s*[:=]\\s*'), sub("  'pass pair': /(?:pass|pw)(?:\\s*[\"']|=)/i,", "  'pass pair': /(?:pass|pw)/i,")) },
  { id: 'AC10-wifi-qr-dropped', ac: 'AC10', note: 'the text of a Wi-Fi QR code is shown', f: sub("['wifi credentials', ':',", "['wifi credentials', 'zzzz',") },
  // ---- review round 3: the stylesheet. The seven reviewer mutants (R3-C1 to R3-C7) and the kinds of change the reviewer's list names. The first group can reach the
  // strip (the semantic net and the pin both report them); the second group cannot (only the pin does); the third changes the strip element itself.
  { id: 'AC6-css-r3-c1-uppercase-mode-and-rotate', ac: 'AC6', note: 'R3-C1: [DATA-MODE=geek] (attribute names are case-insensitive) picks the strip by role and rotates it edge-on', f: sub('.alert-head{font-weight:700}', '.alert-head{font-weight:700}\n.shell[DATA-MODE="geek"]>[role=region]{transform:rotateX(90deg)}') },
  { id: 'AC6-css-r3-c2-tiny-font', ac: 'AC6', note: 'R3-C2: the strip, picked by aria-live in Geek Mode, gets a font that cannot be read', f: sub('.alert-head{font-weight:700}', '.alert-head{font-weight:700}\n.shell[DATA-MODE=geek]>[aria-live]{font-size:.01px}') },
  { id: 'AC6-css-r3-c3-transparent-text', ac: 'AC6', note: 'R3-C3: the strip text is fully transparent, in both modes', f: sub('.alert-head{font-weight:700}', '.alert-head{font-weight:700}\ndiv[aria-live]{color:rgba(0,0,0,0)}') },
  { id: 'AC6-css-r3-c4-scaled-away', ac: 'AC6', note: 'R3-C4: the strip is scaled to a thousandth', f: sub('.alert-head{font-weight:700}', '.alert-head{font-weight:700}\n[aria-live]{transform:scale(.001)}') },
  { id: 'AC6-css-r3-c5-order-below-body', ac: 'AC6', note: 'R3-C5: the strip is ordered after the Geek body in Geek Mode, far below the first screen', f: sub('.alert-head{font-weight:700}', '.alert-head{font-weight:700}\n.shell[DATA-MODE=geek]>[aria-live]{order:99}') },
  { id: 'AC6-css-r3-c7-blur', ac: 'AC6', note: 'R3-C7: the strip is blurred out', f: sub('.alert-head{font-weight:700}', '.alert-head{font-weight:700}\n[aria-live]{filter:blur(40px)}') },
  { id: 'AC6-css-r3-clip-path', ac: 'AC6', note: 'the strip is clipped away with clip-path', f: sub('.alert-head{font-weight:700}', '.alert-head{font-weight:700}\n[role=region]{clip-path:circle(0)}') },
  { id: 'AC6-css-r3-mask', ac: 'AC6', note: 'the strip is masked with a transparent gradient', f: sub('.alert-head{font-weight:700}', '.alert-head{font-weight:700}\n.shell>[aria-live]{-webkit-mask-image:linear-gradient(transparent,transparent)}') },
  { id: 'AC6-css-r3-line-height-zero', ac: 'AC6', note: 'the alert lines collapse with line-height 0', f: sub('.alert-head{font-weight:700}', '.alert-head{font-weight:700;line-height:0}') },
  { id: 'AC6-css-r3-visibility-in-pinned-rule', ac: 'AC6', note: 'a pinned strip rule gets visibility:hidden (the declaration, not the selector, is new)', f: sub('.alerts{display:grid;gap:8px;min-width:0}', '.alerts{display:grid;gap:8px;min-width:0;visibility:hidden}') },
  { id: 'AC6-css-r3-content-visibility', ac: 'AC6', note: 'content-visibility:hidden on the shell child that is the strip', f: sub('.alert-head{font-weight:700}', '.alert-head{font-weight:700}\n.shell>*{content-visibility:hidden}') },
  { id: 'AC6-css-r3-contain-size', ac: 'AC6', note: 'size containment collapses the strip to nothing', f: sub('.alert-head{font-weight:700}', '.alert-head{font-weight:700}\n.alerts{contain:size}') },
  { id: 'AC6-css-r3-important-display', ac: 'AC6', note: 'a harmless value on a pinned rule, but !important', f: sub('.alerts{display:grid;gap:8px;min-width:0}', '.alerts{display:grid!important;gap:8px;min-width:0}') },
  { id: 'AC6-css-r3-escape-property', ac: 'AC6', note: 'a CSS escape spells display:none in a way the old reader did not see', f: sub('.alert-head{font-weight:700}', '.alert-head{font-weight:700}\n.alerts{d\\\\isplay:none}') },
  { id: 'AC6-css-r3-comment-in-property', ac: 'AC6', note: 'a comment between the property and its colon', f: sub('.alert-head{font-weight:700}', '.alert-head{font-weight:700}\n.alerts{display/**/:none}') },
  { id: 'AC6-css-r3-import', ac: 'AC6', note: 'an @import ahead of a hiding rule used to hide the rule from the old reader', f: sub('.alert-head{font-weight:700}', '.alert-head{font-weight:700}\n@import "x.css";.alerts{display:none}') },
  { id: 'AC6-css-r3-unpinned-media', ac: 'AC6', note: 'a media condition nobody pinned', f: sub('.alert-head{font-weight:700}', '.alert-head{font-weight:700}\n@media (min-width:1px){.alerts{height:0;overflow:hidden}}') },
  { id: 'AC6-css-r3-nested-rule', ac: 'AC6', note: 'a nested rule (CSS nesting) inside a harmless one', f: sub('.alert-head{font-weight:700}', '.alert-head{font-weight:700}\n.shell{.alerts{display:none}}') },
  { id: 'AC6-css-r3-off-strip-value-changed', ac: 'AC6', note: 'a value changes on a rule that cannot reach the strip (only the pin sees it)', f: sub('.title{margin:0;font-size:1.15rem;', '.title{margin:0;font-size:1.16rem;') },
  { id: 'AC6-css-r3-off-strip-new-rule', ac: 'AC6', note: 'a new harmless rule on a class the strip cannot carry (only the pin sees it)', f: sub('.alert-head{font-weight:700}', '.alert-head{font-weight:700}\n.zz-new{margin:0}') },
  { id: 'AC6-css-r3-two-colours-equal', ac: 'AC6', note: 'text and surface get the same colour (each is allowed on its own; the pin sees the change)', f: sub('.alert-action{margin:0;color:var(--ecco-fg2);', '.alert-action{margin:0;color:var(--ecco-surface);') },
  { id: 'AC6-strip-style-attribute', ac: 'AC6', note: 'the strip element gets an inline style attribute', f: sub("'aria-label': 'Safety and status alerts', 'aria-live': 'polite' });", "'aria-label': 'Safety and status alerts', 'aria-live': 'polite', style: 'height:0;overflow:hidden' });") },
  { id: 'AC6-strip-alert-node-inert', ac: 'AC6', note: 'an alert node gets the hidden attribute', f: sub("role: critical ? 'alert' : 'status' })", "role: critical ? 'alert' : 'status', hidden: critical })") },
  // ---- review round 4: what a screen reader gets from the strip (reviewer mutants J2 and J5, and the ways around the same net). Each is planted after the line that
  // shows the Geek body, so it runs on every mode change; the first two are the reviewer's own and survived every suite of round 3.
  { id: 'AC6-aria-r4-J2-strip-aria-hidden-in-geek', ac: 'AC6', note: 'J2: aria-hidden on the strip in Geek Mode (a screen reader gets no safety alert)', f: sub(GEEK_LINE, `${GEEK_LINE}\n    ui.strip.setAttribute('aria-hidden', mode === 'geek' ? 'true' : 'false');`) },
  { id: 'AC6-aria-r4-J5-strip-live-off-in-geek', ac: 'AC6', note: 'J5: aria-live off in Geek Mode (new alerts are no longer announced)', f: sub(GEEK_LINE, `${GEEK_LINE}\n    ui.strip.setAttribute('aria-live', mode === 'geek' ? 'off' : 'polite');`) },
  { id: 'AC6-aria-r4-live-assertive-in-geek', ac: 'AC6', note: 'aria-live changes to assertive in Geek Mode only', f: sub(GEEK_LINE, `${GEEK_LINE}\n    ui.strip.setAttribute('aria-live', mode === 'geek' ? 'assertive' : 'polite');`) },
  { id: 'AC6-aria-r4-live-removed-in-geek', ac: 'AC6', note: 'aria-live removed in Geek Mode', f: sub(GEEK_LINE, `${GEEK_LINE}\n    if (mode === 'geek') ui.strip.removeAttribute('aria-live');`) },
  { id: 'AC6-aria-r4-shell-aria-hidden-in-geek', ac: 'AC6', note: 'aria-hidden on the shell (which holds the strip) in Geek Mode', f: sub(GEEK_LINE, `${GEEK_LINE}\n    ui.shell.setAttribute('aria-hidden', mode === 'geek' ? 'true' : 'false');`) },
  { id: 'AC6-aria-r4-strip-inert-in-geek', ac: 'AC6', note: 'inert toggled on the strip in Geek Mode', f: sub(GEEK_LINE, `${GEEK_LINE}\n    ui.strip.toggleAttribute('inert', mode === 'geek');`) },
  { id: 'AC6-aria-r4-host-inert-in-geek', ac: 'AC6', note: 'inert on the card element itself in Geek Mode', f: sub(GEEK_LINE, `${GEEK_LINE}\n    if (mode === 'geek') this.setAttribute('inert', '');`) },
  { id: 'AC6-aria-r4-role-none-in-geek', ac: 'AC6', note: 'role presentation on the strip in Geek Mode', f: sub(GEEK_LINE, `${GEEK_LINE}\n    ui.strip.setAttribute('role', mode === 'geek' ? 'presentation' : 'region');`) },
  { id: 'AC6-aria-r4-label-empty-in-geek', ac: 'AC6', note: 'the strip label emptied in Geek Mode', f: sub(GEEK_LINE, `${GEEK_LINE}\n    ui.strip.setAttribute('aria-label', mode === 'geek' ? '' : 'Safety and status alerts');`) },
  { id: 'AC6-aria-r4-reflection-aria-hidden', ac: 'AC6', note: 'aria-hidden through the ariaHidden property (the DOM stand-in sees no attribute: only the source guard can)', f: sub(GEEK_LINE, `${GEEK_LINE}\n    ui.strip.ariaHidden = mode === 'geek' ? 'true' : 'false';`) },
  { id: 'AC6-aria-r4-reflection-aria-live', ac: 'AC6', note: 'aria-live through the ariaLive property', f: sub(GEEK_LINE, `${GEEK_LINE}\n    ui.strip.ariaLive = mode === 'geek' ? 'off' : 'polite';`) },
  { id: 'AC6-aria-r4-reflection-role', ac: 'AC6', note: 'the role through the role property', f: sub(GEEK_LINE, `${GEEK_LINE}\n    ui.strip.role = mode === 'geek' ? 'none' : 'region';`) },
  { id: 'AC6-aria-r4-name-in-template-literal', ac: 'AC6', note: 'the attribute name is a template literal, which a literal-name scan would skip', f: sub(GEEK_LINE, `${GEEK_LINE}\n    ui.strip.setAttribute(\`aria-hidden\`, mode === 'geek' ? 'true' : 'false');`) },
  { id: 'AC6-aria-r4-name-by-concatenation', ac: 'AC6', note: 'the attribute name is built by concatenation', f: sub(GEEK_LINE, `${GEEK_LINE}\n    ui.strip.setAttribute('aria-' + 'hidden', mode === 'geek' ? 'true' : 'false');`) },
  { id: 'AC6-aria-r4-alias-of-set-attribute', ac: 'AC6', note: 'setAttribute reached through an alias', f: sub(GEEK_LINE, `${GEEK_LINE}\n    const sa = ui.strip.setAttribute;\n    sa.call(ui.strip, 'aria-hidden', mode === 'geek' ? 'true' : 'false');`) },
  { id: 'AC6-aria-r4-strip-literal-aria-hidden', ac: 'AC6', note: 'aria-hidden false added to the strip literal (present in both modes)', f: sub("'aria-label': 'Safety and status alerts', 'aria-live': 'polite' });", "'aria-label': 'Safety and status alerts', 'aria-live': 'polite', 'aria-hidden': 'false' });") },
  { id: 'AC6-aria-r4-strip-literal-live-off', ac: 'AC6', note: 'the strip literal says aria-live off in both modes', f: sub("'aria-label': 'Safety and status alerts', 'aria-live': 'polite' });", "'aria-label': 'Safety and status alerts', 'aria-live': 'off' });") },
  { id: 'AC6-aria-r4-strip-literal-no-label', ac: 'AC6', note: 'the strip literal loses its label', f: sub("role: 'region', 'aria-label': 'Safety and status alerts', 'aria-live': 'polite' });", "role: 'region', 'aria-live': 'polite' });") },
  { id: 'AC6-aria-r4-alert-role-presentation', ac: 'AC6', note: 'every alert line is given role presentation', f: sub("role: critical ? 'alert' : 'status' })", "role: 'presentation' })") },
  { id: 'AC6-aria-r4-alert-node-aria-hidden', ac: 'AC6', note: 'aria-hidden on every alert line', f: sub("role: critical ? 'alert' : 'status' })", "role: critical ? 'alert' : 'status', 'aria-hidden': 'true' })") },
  // ---- review round 4: a MAC address written with spaces (reviewer probe), and the look-alikes the rule must leave alone
  { id: 'AC10-mac-spaced-dropped', ac: 'AC10', note: 'a MAC address written with spaces is shown', f: sub("['MAC address (spaced)', ' ',", "['MAC address (spaced)', 'zzzz',") },
  { id: 'AC10-mac-spaced-takes-numbers', ac: 'AC10', note: 'the spaced-MAC rule needs no letter, so six two-digit numbers are withheld', f: sub('(?=[0-9a-f ]{0,16}[a-f])(?:[0-9a-f]{2} ){5}', '(?:[0-9a-f]{2} ){5}') },
  { id: 'AC10-mac-spaced-starts-mid-group', ac: 'AC10', note: 'the spaced-MAC rule may start inside a longer group of digits', f: sub('(?<![0-9a-f])(?=[0-9a-f ]{0,16}[a-f])', '(?=[0-9a-f ]{0,16}[a-f])') },
  { id: 'AC10-mac-spaced-ends-mid-group', ac: 'AC10', note: 'the spaced-MAC rule may end inside a longer group of digits', f: sub('(?:[0-9a-f]{2} ){5}[0-9a-f]{2}(?![0-9a-f])/i]', '(?:[0-9a-f]{2} ){5}[0-9a-f]{2}/i]') },
  { id: 'AC6-aria-r4-render-strip-aria-hidden', ac: 'AC6', note: 'the one strip renderer hides the strip from assistive technology on every render, in both modes', f: sub("strip.setAttribute('data-alert-count', String(alerts.length));", "strip.setAttribute('data-alert-count', String(alerts.length));\n  strip.setAttribute('aria-hidden', 'true');") },
  // ---- review round 5: a secret deep inside a long string. The card reads every string whole (up to the 4000-character cap): each of these reads only a part of it. The reviewer's R14,
  // R15 and R16 (the first 64, 300 and 1000 characters) survived all five suites of round 4; the hostile fixtures of rounds 1 to 4 all have their secret at the start of the string.
  { id: 'AC10-r5-R14-scan-first-64', ac: 'AC10', note: 'R14: only the first 64 characters of a string are read for secrets', f: sub(SCAN_LINE, SCAN_LINE.replace('valueReason(t,', 'valueReason(t.slice(0, 64),')) },
  { id: 'AC10-r5-R15-scan-first-300', ac: 'AC10', note: 'R15: only the first 300 characters are read', f: sub(SCAN_LINE, SCAN_LINE.replace('valueReason(t,', 'valueReason(t.slice(0, 300),')) },
  { id: 'AC10-r5-R16-scan-first-1000', ac: 'AC10', note: 'R16: only the first 1000 characters are read', f: sub(SCAN_LINE, SCAN_LINE.replace('valueReason(t,', 'valueReason(t.slice(0, 1000),')) },
  { id: 'AC10-r5-R17-scan-last-64', ac: 'AC10', note: 'R17: only the last 64 characters are read', f: sub(SCAN_LINE, SCAN_LINE.replace('valueReason(t,', 'valueReason(t.slice(-64),')) },
  { id: 'AC10-r5-R18-scan-last-1000', ac: 'AC10', note: 'R18: only the last 1000 characters are read', f: sub(SCAN_LINE, SCAN_LINE.replace('valueReason(t,', 'valueReason(t.slice(-1000),')) },
  { id: 'AC10-r5-R19-scan-first-3900', ac: 'AC10', note: 'R19: the last 100 characters of a string that fits the cap are not read', f: sub(SCAN_LINE, SCAN_LINE.replace('valueReason(t,', 'valueReason(t.slice(0, 3900),')) },
  { id: 'AC10-r5-R20-scan-first-3999', ac: 'AC10', note: 'R20: the very last character of a string that fits the cap is not read', f: sub(SCAN_LINE, SCAN_LINE.replace('valueReason(t,', 'valueReason(t.slice(0, 3999),')) },
  { id: 'AC10-r5-scan-middle-only', ac: 'AC10', note: 'only the middle of a long string is read (the first and last 500 characters are skipped)', f: sub(SCAN_LINE, SCAN_LINE.replace('valueReason(t,', 'valueReason(t.length > 1500 ? t.slice(500, -500) : t,')) },
  { id: 'AC10-r5-cap-raised', ac: 'AC10', note: 'the cap is raised, so text past 4000 characters is kept and read (the cut is no longer said)', f: sub('  stringCap: 4000,', '  stringCap: 400000,') },
  // ---- review round 5, NIT: a catalogue pattern with overlapping alternatives took 274 ms on a 36-character key, and the time doubles with each character (reviewer probe probe-redos)
  // ---- review round 5, NIT: a configuration problem was collected and never shown
  { id: 'AC16-r5-config-errors-not-shown', ac: 'AC16', note: 'a configuration problem (production given as text) leaves no line on the strip', f: sub('    if (cfg.errors.length) {', '    if (false) {') },
  { id: 'AC16-r5-config-errors-only-first', ac: 'AC16', note: 'the strip line names only the first problem and never says how many there are', f: sub("  const shown = errors.slice(0, 3).map((e) => `${e.path}: ${e.message}`).join('; ');", "  const shown = errors.slice(0, 1).map((e) => `${e.path}: ${e.message}`).join('; ');") },
  // ---- review round 5: the five mutants that only the opt-in browser check caught (J13, J14, J20, J21, AR08), now also killed by the node suites. `browser: true` marks the ones the
  // browser check is asked about too when Chrome or Edge is installed (the extra layer: it must fail them as well; the node suites alone must already kill them)
  { id: 'AC6-r5-J13-inline-property-on-shell', ac: 'AC6', browser: true, note: 'J13: the Geek header sets --ecco-fg to transparent on the shell, from the call that sets --ecco-w on a bar segment', f: sub("seg.style.setProperty('--ecco-w', String(c[s]));", "this.o.container.parentNode.style.setProperty('--ecco-fg', String('rgba(0,0,0,0)'));") },
  { id: 'AC6-r5-J21-ring-property-on-shell', ac: 'AC6', browser: true, note: 'J21: a tile ring sets --ecco-accent to transparent on the shell instead of --ecco-p on the ring', f: sub("if (ring.mode === 'percent') ringEl.style.setProperty('--ecco-p', String(ring.pct));", "if (ring.mode === 'percent') this.o.container.parentNode.style.setProperty('--ecco-accent', String('transparent'));") },
  { id: 'AC6-r5-setproperty-name-changed', ac: 'AC6', note: 'the bar segment call sets another --ecco property (the receiver is right, the name is not)', f: sub("seg.style.setProperty('--ecco-w', String(c[s]));", "seg.style.setProperty('--ecco-fg', String(c[s]));") },
  { id: 'AC6-r5-setproperty-receiver-changed', ac: 'AC6', note: 'the ring call sets --ecco-p on the tile instead of the ring', f: sub("if (ring.mode === 'percent') ringEl.style.setProperty('--ecco-p', String(ring.pct));", "if (ring.mode === 'percent') el.style.setProperty('--ecco-p', String(ring.pct));") },
  { id: 'AC6-r5-setproperty-added', ac: 'AC6', note: 'a third inline custom property is set (a number, so the old pattern accepted it)', f: sub("      if (ring.mode === 'percent')", "      ringEl.style.setProperty('--ecco-q', String(1));\n      if (ring.mode === 'percent')") },
  { id: 'AC6-r5-J14-strip-moved-last-in-geek', ac: 'AC6', browser: true, note: 'J14: in Geek Mode the strip is moved to the end of the shell, after the Geek body', f: sub(GEEK_LINE, `${GEEK_LINE}\n    if (mode === 'geek') ui.shell.appendChild(ui.strip); else ui.shell.insertBefore(ui.strip, ui.always);`) },
  { id: 'AC6-r5-J20-strip-before-geek-body', ac: 'AC6', browser: true, note: 'J20: in Geek Mode the strip is moved to just before the Geek body, after the always region and the Production body', f: sub(GEEK_LINE, `${GEEK_LINE}\n    if (mode === 'geek') ui.shell.insertBefore(ui.strip, ui.geekBody); else ui.shell.insertBefore(ui.strip, ui.always);`) },
  { id: 'AC6-r5-strip-moved-into-always', ac: 'AC6', note: 'in Geek Mode the strip is moved into the always region (still on screen, no longer a child of the shell)', f: sub(GEEK_LINE, `${GEEK_LINE}\n    if (mode === 'geek') ui.always.appendChild(ui.strip); else ui.shell.insertBefore(ui.strip, ui.always);`) },
  { id: 'AC6-r5-strip-moved-above-top', ac: 'AC6', note: 'in Geek Mode the strip is moved above the title and the switch', f: sub(GEEK_LINE, `${GEEK_LINE}\n    if (mode === 'geek') ui.shell.insertBefore(ui.strip, ui.shell.firstChild); else ui.shell.insertBefore(ui.strip, ui.always);`) },
  { id: 'AC6-r5-AR08-strip-shadow-root-in-geek', ac: 'AC6', browser: true, note: 'AR08: attachShadow on the strip in Geek Mode (a shadow root with no slot empties it in a browser)', f: sub(GEEK_LINE, `${GEEK_LINE}\n    if (mode === 'geek' && !ui.strip.shadowRoot && typeof ui.strip.attachShadow === 'function') ui.strip.attachShadow({ mode: 'open' });`) },
  { id: 'AC6-r5-shadow-root-on-strip-at-build', ac: 'AC6', note: 'attachShadow on the strip when the shell is built (not in the constructor of the card)', f: sub('    this._root.replaceChildren(style, shell);', "    this._root.replaceChildren(style, shell);\n    if (typeof strip.attachShadow === 'function') strip.attachShadow({ mode: 'closed' });") },
  { id: 'AC6-r5-shadow-root-on-shell', ac: 'AC6', note: 'attachShadow on the shell element (a second shadow root in the tree)', f: sub('    this._root.replaceChildren(style, shell);', "    this._root.replaceChildren(style, shell);\n    if (typeof shell.attachShadow === 'function') shell.attachShadow({ mode: 'open' });") },
  // ---- review round 6 (design section 18): the SWEEP and the plain-fragment rule. Every mutant below that reads only a part of a string is a SCAN VARIANT of the class the sweep closes: a prefix, a suffix, a window, chunks (with and
  // without an overlap), a middle, the ends only, lines, words, an off-by-one. The reviewer's S01, S02, S06, S07 survived all five suites of round 5; the others are the variants of the same class that no reviewer has named yet.
  { id: 'AC10-r6-S01-skip-first-char-long', ac: 'AC10', note: 'S01: a text of more than 1000 characters is read from its second character', f: sub(SCAN_LINE, SCAN_LINE.replace('valueReason(t,', 'valueReason(t.length > 1000 ? t.slice(1) : t,')) },
  { id: 'AC10-r6-S02-last-3999', ac: 'AC10', note: 'S02: only the last 3999 characters are read (off by one at the cap)', f: sub(SCAN_LINE, SCAN_LINE.replace('valueReason(t,', 'valueReason(t.slice(-3999),')) },
  { id: 'AC10-r6-S03-window-50-3950', ac: 'AC10', note: 'S03: a long text is read from character 50 to 3950', f: sub(SCAN_LINE, SCAN_LINE.replace('valueReason(t,', 'valueReason(t.length > 200 ? t.slice(50, 3950) : t,')) },
  { id: 'AC10-r6-S04-per-line', ac: 'AC10', note: 'S04: each line is read alone', f: sub(SCAN_LINE, "  if (t.split('\\n').some((l) => valueReason(l, digestOk, digestKey) !== null)) return WITHHELD;") },
  { id: 'AC10-r6-S05-split-at-spaces', ac: 'AC10', note: 'S05: each word is read alone', f: sub(SCAN_LINE, "  if (t.split(' ').some((l) => valueReason(l, digestOk, digestKey) !== null)) return WITHHELD;") },
  { id: 'AC10-r6-S06-chunks-500', ac: 'AC10', note: 'S06: the text is read in chunks of 500 characters with no overlap', f: sub(SCAN_LINE, '  { let hit = false; for (let i = 0; i < t.length; i += 500) if (valueReason(t.slice(i, i + 500), digestOk, digestKey) !== null) hit = true; if (hit) return WITHHELD; }') },
  { id: 'AC10-r6-S07-chunks-1000', ac: 'AC10', note: 'S07: the text is read in chunks of 1000 characters with no overlap', f: sub(SCAN_LINE, '  { let hit = false; for (let i = 0; i < t.length; i += 1000) if (valueReason(t.slice(i, i + 1000), digestOk, digestKey) !== null) hit = true; if (hit) return WITHHELD; }') },
  { id: 'AC10-r6-chunks-256', ac: 'AC10', note: 'chunks of 256 characters with no overlap', f: sub(SCAN_LINE, '  { let hit = false; for (let i = 0; i < t.length; i += 256) if (valueReason(t.slice(i, i + 256), digestOk, digestKey) !== null) hit = true; if (hit) return WITHHELD; }') },
  { id: 'AC10-r6-chunks-1024', ac: 'AC10', note: 'chunks of 1024 characters with no overlap', f: sub(SCAN_LINE, '  { let hit = false; for (let i = 0; i < t.length; i += 1024) if (valueReason(t.slice(i, i + 1024), digestOk, digestKey) !== null) hit = true; if (hit) return WITHHELD; }') },
  { id: 'AC10-r6-chunks-4000', ac: 'AC10', note: 'chunks of 4000 characters with no overlap (the display cap as a chunk)', f: sub(SCAN_LINE, '  { let hit = false; for (let i = 0; i < t.length; i += 4000) if (valueReason(t.slice(i, i + 4000), digestOk, digestKey) !== null) hit = true; if (hit) return WITHHELD; }') },
  { id: 'AC10-r6-chunks-500-overlap-20', ac: 'AC10', note: 'chunks of 500 characters that overlap by 20 (a secret longer than the overlap can straddle an edge unseen)', f: sub(SCAN_LINE, '  { let hit = false; for (let i = 0; i < t.length; i += 480) if (valueReason(t.slice(i, i + 500), digestOk, digestKey) !== null) hit = true; if (hit) return WITHHELD; }') },
  { id: 'AC10-r6-chunks-1000-overlap-40', ac: 'AC10', note: 'chunks of 1000 characters that overlap by 40', f: sub(SCAN_LINE, '  { let hit = false; for (let i = 0; i < t.length; i += 960) if (valueReason(t.slice(i, i + 1000), digestOk, digestKey) !== null) hit = true; if (hit) return WITHHELD; }') },
  { id: 'AC10-r6-S08-first-3990-when-long', ac: 'AC10', note: 'S08: a text of 3999 characters or more is read to character 3990 only', f: sub(SCAN_LINE, SCAN_LINE.replace('valueReason(t,', 'valueReason(t.length >= 3999 ? t.slice(0, 3990) : t,')) },
  { id: 'AC10-r6-first-4000', ac: 'AC10', note: 'only the first 4000 characters are read (the round-5 reader: a secret beyond the display cap is not seen)', f: sub(SCAN_LINE, SCAN_LINE.replace('valueReason(t,', 'valueReason(t.slice(0, 4000),')) },
  { id: 'AC10-r6-first-19999', ac: 'AC10', note: 'the last character of a text of 20000 characters is not read', f: sub(SCAN_LINE, SCAN_LINE.replace('valueReason(t,', 'valueReason(t.slice(0, 19999),')) },
  { id: 'AC10-r6-last-19999', ac: 'AC10', note: 'the first character of a text of 20000 characters is not read', f: sub(SCAN_LINE, SCAN_LINE.replace('valueReason(t,', 'valueReason(t.slice(-19999),')) },
  { id: 'AC10-r6-ends-only-1000', ac: 'AC10', note: 'only the first and the last 1000 characters are read (the middle is skipped)', f: sub(SCAN_LINE, SCAN_LINE.replace('valueReason(t,', 'valueReason(t.length > 2000 ? t.slice(0, 1000) + t.slice(-1000) : t,')) },
  { id: 'AC10-r6-middle-window-1000-3000', ac: 'AC10', note: 'only characters 1000 to 3000 of a long text are read', f: sub(SCAN_LINE, SCAN_LINE.replace('valueReason(t,', 'valueReason(t.length > 3000 ? t.slice(1000, 3000) : t,')) },
  { id: 'AC10-r6-off-by-one-end', ac: 'AC10', note: 'the last character is never read (a secret that ends the text)', f: sub(SCAN_LINE, SCAN_LINE.replace('valueReason(t,', 'valueReason(t.slice(0, -1),')) },
  { id: 'AC10-r6-off-by-one-start', ac: 'AC10', note: 'the first character is never read (a secret that starts the text)', f: sub(SCAN_LINE, SCAN_LINE.replace('valueReason(t,', 'valueReason(t.slice(1),')) },
  // ---- review round 6, NIT-2: read first, cut after, and a hard bound
  { id: 'AC10-r6-truncate-before-scan', ac: 'AC10', note: 'the text is cut at the display cap BEFORE it is read (the round-5 order: a secret that crosses the cap leaves a part of itself in view)', f: sub('  const t = s;\n', '  const t = s.length > LIMITS.stringCap ? s.slice(0, LIMITS.stringCap) : s;\n') },
  { id: 'AC10-r6-no-hard-bound', ac: 'AC10', note: 'a text of any length is read (no hard bound: a 600000-character text costs a full scan)', f: sub('  if (s.length > LIMITS.scanBound) return WITHHELD;\n', '') },
  { id: 'AC10-r6-bound-raised', ac: 'AC10', note: 'the hard bound is a million characters', f: sub('  scanBound: 20000,', '  scanBound: 1000000,') },
  { id: 'AC10-r6-bound-lowered-to-cap', ac: 'AC10', note: 'the hard bound is the display cap (a harmless text of 4500 characters is withheld)', f: sub('  scanBound: 20000,', '  scanBound: 4000,') },
  { id: 'AC10-r6-bound-off-by-one', ac: 'AC10', note: 'a text of exactly the bound is withheld', f: sub('  if (s.length > LIMITS.scanBound) return WITHHELD;', '  if (s.length >= LIMITS.scanBound) return WITHHELD;') },
  { id: 'AC10-r6-bound-shown-truncated', ac: 'AC10', note: 'a text beyond the bound is cut at the bound and read (the first 20000 characters), not withheld', f: chain(sub('  if (s.length > LIMITS.scanBound) return WITHHELD;\n', ''), sub('  const t = s;\n', '  const t = s.length > LIMITS.scanBound ? s.slice(0, LIMITS.scanBound) : s;\n')) },
  { id: 'AC10-r6-key-bound-dropped', ac: 'AC10', note: 'a key name of any length is read (no bound on a key)', f: sub('  if (String(key).length > LIMITS.scanBound) return true;\n', '') },
  { id: 'AC10-r6-key-bound-raised', ac: 'AC10', note: 'a key name is read up to a million characters', f: sub('  if (String(key).length > LIMITS.scanBound) return true;', '  if (String(key).length > 1000000) return true;') },
  { id: 'AC10-r6-keyname-scan-first-64', ac: 'AC10', note: 'only the first 64 characters of a key NAME are read for secrets', f: sub('else if (valueReason(k.length > 200 ? k.slice(0, 200) : k, false) !== null) {', 'else if (valueReason(k.length > 64 ? k.slice(0, 64) : k, false) !== null) {') },
  { id: 'AC10-r6-keyname-scan-first-100', ac: 'AC10', note: 'only the first 100 characters of a key NAME are read (secrets that start inside the 120 shown are partly seen)', f: sub('else if (valueReason(k.length > 200 ? k.slice(0, 200) : k, false) !== null) {', 'else if (valueReason(k.length > 100 ? k.slice(0, 100) : k, false) !== null) {') },
  { id: 'AC10-r6-keyname-scan-last-100', ac: 'AC10', note: 'only the last 100 characters of a long key NAME are read', f: sub('else if (valueReason(k.length > 200 ? k.slice(0, 200) : k, false) !== null) {', 'else if (valueReason(k.length > 200 ? k.slice(-100) : k, false) !== null) {') },
  // the three read-ahead rules and their pre-tests (a text of 20000 characters that only looks like the start of one is not walked once per start)
  { id: 'AC12-r6-pretest-host-dropped', ac: 'AC12', note: 'the private host name rule has no pre-test (a long dotted text costs a quadratic walk)', f: sub("  'private host name': /\\.(?:local|lan|internal|home\\.arpa|localdomain)\\b/i,\n", '') },
  { id: 'AC12-r6-pretest-mac-dropped', ac: 'AC12', note: 'the dotted MAC rule has no pre-test', f: sub("  'MAC address (dotted)': /[0-9a-f]{4}\\.[0-9a-f]{4}\\.[0-9a-f]{4}/i,\n", '') },
  { id: 'AC12-r6-pretest-pass-dropped', ac: 'AC12', note: 'the pass pair rule has no pre-test', f: sub("  'pass pair': /(?:pass|pw)(?:\\s*[\"']|=)/i,\n", '') },
  { id: 'AC10-r6-pretest-pass-too-strict', ac: 'AC10', note: 'the pass pair pre-test requires an equals sign (a quoted pass pair is never tried)', f: sub("  'pass pair': /(?:pass|pw)(?:\\s*[\"']|=)/i,", "  'pass pair': /(?:pass|pw)=/i,") },
  { id: 'AC10-r6-pretest-host-too-strict', ac: 'AC10', note: 'the private host name pre-test knows only .local', f: sub("  'private host name': /\\.(?:local|lan|internal|home\\.arpa|localdomain)\\b/i,", "  'private host name': /\\.local\\b/i,") },
  { id: 'AC12-r6-pretest-never-consulted', ac: 'AC12', note: 'the pre-test table is built and never asked', f: sub('    if (PRETEST[i] !== undefined && !PRETEST[i].test(s)) continue;\n', '') },
  { id: 'AC10-r6-pretest-misaligned', ac: 'AC10', note: 'the pre-test of one rule is asked for the next one (the table is shifted by a row)', f: sub('    if (PRETEST[i] !== undefined && !PRETEST[i].test(s)) continue;', '    if (PRETEST[i + 1] !== undefined && !PRETEST[i + 1].test(s)) continue;') },
  // ---- review round 6, NIT-1 and the K02 class: a catalogue pattern is a PLAIN FRAGMENT, matched as a part of the key name; the key is read in windows of 200 characters that overlap by 79
  { id: 'AC10-r6-K02-whole-key-window', ac: 'AC10', note: 'K02: a fragment is searched in the whole key at once (no window)', f: sub('    const w = lower.slice(i, i + EXTRA_KEY_CAP);', '    const w = lower;') },
  { id: 'AC10-r6-K02-unbounded-slice', ac: 'AC10', note: 'K02: each window runs to the end of the key', f: sub('    const w = lower.slice(i, i + EXTRA_KEY_CAP);', '    const w = lower.slice(i);') },
  { id: 'AC10-r6-key-window-500', ac: 'AC10', note: 'the window is 500 characters (the overlap rule keeps it correct, but a fragment is searched in more than 200)', f: sub('const EXTRA_KEY_CAP = 200;', 'const EXTRA_KEY_CAP = 500;') },
  { id: 'AC10-r6-key-window-no-overlap', ac: 'AC10', note: 'the windows of a long key do not overlap (a fragment that crosses an edge is missed)', f: sub('  const step = EXTRA_KEY_CAP - (EXTRA_FRAGMENT_MAX - 1);', '  const step = EXTRA_KEY_CAP;') },
  { id: 'AC10-r6-key-window-overlap-short-by-one', ac: 'AC10', note: 'the overlap is one character short of the longest fragment (an 80-character fragment can fall between two windows)', f: sub('  const step = EXTRA_KEY_CAP - (EXTRA_FRAGMENT_MAX - 1);', '  const step = EXTRA_KEY_CAP - (EXTRA_FRAGMENT_MAX - 2);') },
  { id: 'AC10-r6-key-head-window-only', ac: 'AC10', note: 'only the first window of a long key is read', f: sub('  for (let i = 0; i < lower.length; i += step) {', '  for (let i = 0; i < 1; i += step) {') },
  { id: 'AC10-r6-key-tail-window-only', ac: 'AC10', note: 'only the last 200 characters of a long key are read', f: sub('  const lower = whole.toLowerCase();\n  const step', '  const lower = (whole.length > EXTRA_KEY_CAP ? whole.slice(-EXTRA_KEY_CAP) : whole).toLowerCase();\n  const step') },
  { id: 'AC10-r6-key-ends-only', ac: 'AC10', note: 'only the first and the last 200 characters of a long key are read (the round-5 design: the middle is skipped)', f: sub('  const lower = whole.toLowerCase();\n  const step', '  const lower = (whole.length > 2 * EXTRA_KEY_CAP ? whole.slice(0, EXTRA_KEY_CAP) + whole.slice(-EXTRA_KEY_CAP) : whole).toLowerCase();\n  const step') },
  { id: 'AC10-r6-key-window-last-skipped', ac: 'AC10', note: 'the loop stops one window early (the end of a key is never read)', f: sub('  for (let i = 0; i < lower.length; i += step) {', '  for (let i = 0; i + EXTRA_KEY_CAP < lower.length; i += step) {') },
  { id: 'AC10-r6-key-case-sensitive', ac: 'AC10', note: 'a fragment is matched case-sensitively', f: sub('  const lower = whole.toLowerCase();', '  const lower = whole;') },
  { id: 'AC10-r6-fragment-any-string', ac: 'AC10', note: 'any string is a fragment (anchors, classes and spaces are accepted and matched as text)', f: sub('const isFragment = (f) => isStr(f) && EXTRA_FRAGMENT.test(f);', 'const isFragment = (f) => isStr(f) && f.length > 0 && f.length <= EXTRA_FRAGMENT_MAX;') },
  { id: 'AC10-r6-fragment-upper-case', ac: 'AC10', note: 'a fragment may hold capitals', f: sub('const EXTRA_FRAGMENT = /^[a-z0-9_]{1,80}$/;', 'const EXTRA_FRAGMENT = /^[a-zA-Z0-9_]{1,80}$/;') },
  { id: 'AC10-r6-fragment-trailing-newline', ac: 'AC10', note: 'a fragment may be followed by a newline (the Python $ allows it; the JavaScript one must not)', f: sub('const EXTRA_FRAGMENT = /^[a-z0-9_]{1,80}$/;', 'const EXTRA_FRAGMENT = /^[a-z0-9_]{1,80}\\n?$/;') },
  { id: 'AC10-r6-fragment-multiline', ac: 'AC10', note: 'the fragment rule is read line by line (a second line may be anything)', f: sub('const EXTRA_FRAGMENT = /^[a-z0-9_]{1,80}$/;', 'const EXTRA_FRAGMENT = /^[a-z0-9_]{1,80}$/m;') },
  { id: 'AC10-r6-fragment-empty', ac: 'AC10', note: 'the empty fragment is accepted (it is a part of every key)', f: sub('const EXTRA_FRAGMENT = /^[a-z0-9_]{1,80}$/;', 'const EXTRA_FRAGMENT = /^[a-z0-9_]{0,80}$/;') },
  { id: 'AC10-r6-fragment-81', ac: 'AC10', note: 'a fragment may be 81 characters', f: sub('const EXTRA_FRAGMENT = /^[a-z0-9_]{1,80}$/;', 'const EXTRA_FRAGMENT = /^[a-z0-9_]{1,81}$/;') },
  { id: 'AC10-r6-fragment-count-41', ac: 'AC10', note: 'forty-one fragments are read', f: sub('  for (const f of list.slice(0, EXTRA_FRAGMENTS_MAX)) if (isFragment(f)) out.push(f);', '  for (const f of list.slice(0, EXTRA_FRAGMENTS_MAX + 1)) if (isFragment(f)) out.push(f);') },
  { id: 'AC10-r6-fragment-count-unbounded', ac: 'AC10', note: 'every fragment of the list is read, however many', f: sub('  for (const f of list.slice(0, EXTRA_FRAGMENTS_MAX)) if (isFragment(f)) out.push(f);', '  for (const f of list) if (isFragment(f)) out.push(f);') },
  { id: 'AC10-r6-refused-fragment-silent', ac: 'AC10', note: 'NIT-1: a refused pattern is dropped without a catalogue error', f: sub('      else err(errors, `redaction.extra_key_patterns[${i}]`,', '      else void (`redaction.extra_key_patterns[${i}]`,') },
  { id: 'AC10-r6-too-many-fragments-silent', ac: 'AC10', note: 'more than forty fragments are dropped without a catalogue error', f: sub('    if (list.length > EXTRA_FRAGMENTS_MAX) err(', '    if (false) err(') },
  { id: 'AC10-r6-fragment-list-not-list-silent', ac: 'AC10', note: 'an extra_key_patterns that is not a list is ignored without a catalogue error', f: sub("  } else if (isObj(input.redaction) && input.redaction.extra_key_patterns !== undefined) err(errors, 'redaction.extra_key_patterns', 'extra_key_patterns must be a list of plain key fragments');\n", '  }\n') },
  { id: 'AC10-r6-sanitised-keeps-refused', ac: 'AC10', note: 'the sanitised catalogue keeps a refused pattern beside the fragments', f: sub('      if (isFragment(f)) out.redaction.extra_key_patterns.push(f);\n      else err(', '      out.redaction.extra_key_patterns.push(f);\n      if (!isFragment(f)) err(') },
  { id: 'AC10-r6-error-list-unbounded', ac: 'AC10', note: 'every pattern of a huge list is looked at one by one (a list of a hundred thousand makes a hundred thousand errors)', f: sub('    list.slice(0, EXTRA_FRAGMENTS_MAX).forEach((f, i) => {', '    list.forEach((f, i) => {') },
  { id: 'AC10-r6-tooltip-claims-secret', ac: 'AC10', note: 'the withheld marker says only that the value looks secret (a text that was too long to be checked is not secret)', f: sub("title: 'This value is not shown: it looks secret or private, or it is too long to be checked.' }", "title: 'This value looks secret or private, so it is not shown.' }") },
  { id: 'AC10-r6-expression-from-data', ac: 'AC10', note: 'a catalogue fragment is turned into a regular expression and run (the round-4 shape: code from data)', f: sub('    for (const f of fragments) if (w.includes(f)) return true;', '    for (const f of fragments) if (new RegExp(f, \'i\').test(w)) return true;') },
  // ---- review round 6, P07 and the style class (the structure net and the behaviour net; the first is static.test.mjs, the second is element.test.mjs). `browser: true`: the headless check is asked too
  { id: 'AC6-r6-P07-setproperty-bracket', ac: 'AC6', browser: true, note: 'P07: the bar-segment call is followed by the same call written with a bracket, on the shell', f: sub("seg.style.setProperty('--ecco-w', String(c[s]));", "seg.style.setProperty('--ecco-w', String(c[s])); this.o.container.parentNode.style['setProperty']('--ecco-fg', 'transparent');") },
  { id: 'AC6-r6-P04-style-bracket-colour', ac: 'AC6', note: 'P04: Geek Mode sets the strip colour with a bracket write', f: sub(GEEK_LINE, `${GEEK_LINE}\n    ui.strip.style['color'] = mode === 'geek' ? 'transparent' : '';`) },
  { id: 'AC6-r6-P05-setattribute-style-built', ac: 'AC6', note: 'P05: Geek Mode sets a style attribute on the shell with a name built from pieces', f: sub(GEEK_LINE, `${GEEK_LINE}\n    ui.shell.setAttribute('sty' + 'le', mode === 'geek' ? '--ecco-fg:transparent' : '');`) },
  { id: 'AC6-r6-P06-setproperty-alias', ac: 'AC6', note: 'P06: the style of the shell is held in a local and set through it', f: sub("seg.style.setProperty('--ecco-w', String(c[s]));", "const st = this.o.container.parentNode.style; st.setProperty('--ecco-fg', String(c[s] * 0));") },
  { id: 'AC6-r6-assign-onto-strip-style', ac: 'AC6', note: 'Geek Mode assigns a style onto the strip with Object.assign', f: sub(GEEK_LINE, `${GEEK_LINE}\n    if (mode === 'geek') Object.assign(ui.strip.style, { opacity: '0' });`) },
  { id: 'AC6-r6-host-style-property', ac: 'AC6', note: 'Geek Mode sets --ecco-fg to transparent on the host element, with the call spelled out of reach of the old pin', f: sub(GEEK_LINE, `${GEEK_LINE}\n    if (mode === 'geek') this['style'].setProperty('--ecco-fg', 'transparent');`) },
  { id: 'AC6-r6-style-destructured', ac: 'AC6', note: 'the style of the shell is taken by destructuring and set through the local', f: sub(GEEK_LINE, `${GEEK_LINE}\n    { const { style } = ui.shell; if (mode === 'geek') style.setProperty('--ecco-fg', 'transparent'); }`) },
  { id: 'AC6-r6-P08-attachshadow-bracket', ac: 'AC6', note: 'P08: the strip is given a shadow root by a bracket call', f: sub(GEEK_LINE, `${GEEK_LINE}\n    if (mode === 'geek' && !ui.strip.shadowRoot) { const a = 'attach' + 'Shadow'; if (typeof ui.strip[a] === 'function') ui.strip[a]({ mode: 'open' }); }`) },
  // ---- review round 7. The performance class (`perf: true`: the timing tests of perf.test.mjs are run against these too): each rule written back as it was in round 6, or with its bound taken off, and the scan budget broken in every way it can be
  { id: 'AC12-r7-email-unbounded', ac: 'AC12', perf: true, note: 'the e-mail rule starts at every word boundary of a long local part, as in round 6 (a quadratic walk)', f: sub("/(?<=[A-Za-z0-9._%+-])@[A-Za-z0-9-]+(?:\\.[A-Za-z0-9-]+)*\\.[A-Za-z]{2,}\\b/],", "/\\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\\.[A-Za-z0-9-]+)*\\.[A-Za-z]{2,}\\b/],") },
  { id: 'AC12-r7-mac-dotted-lookahead-unbounded', ac: 'AC12', perf: true, note: 'the dotted MAC look-ahead for a letter runs to the end of the dotted text from every start (the reviewer\'s 73 ms)', f: sub('(?=[0-9a-f.]{0,13}[a-f])', '(?=[0-9a-f.]*[a-f])') },
  { id: 'AC12-r7-private-host-walk', ac: 'AC12', perf: true, note: 'the private host name rule starts at every word boundary and walks the dotted chain, as in round 6', f: sub("/(?<=[a-z0-9-])\\.(?:local|lan|internal|home\\.arpa|localdomain)\\b/i],", "/\\b[a-z0-9-]+(?:\\.[a-z0-9-]+)*\\.(?:local|lan|internal|home\\.arpa|localdomain)\\b/i],") },
  { id: 'AC12-r7-pass-pair-prefix-walk', ac: 'AC12', perf: true, note: 'the unquoted pass pair walks a prefix of segments from every start, as in round 6', f: sub('|(?<![a-z0-9])(?:pass|pw)=', '|(?<![a-z0-9])(?:[a-z0-9]+[_-])*(?:pass|pw)=') },
  { id: 'AC12-r7-url-credentials-scheme-run', ac: 'AC12', perf: true, note: 'the url credentials rule reads the scheme as a run from every word boundary, as in round 6 (quadratic on a.a.a.a...)', f: sub("['url credentials', '@', /[a-z0-9+.-]:\\/\\/[^\\s/?#@]*@/i],", "['url credentials', '@', /\\b[a-z][a-z0-9+.-]*:\\/\\/[^\\s/?#@]*@/i],") },
  { id: 'AC12-r7-internal-host-scheme-run', ac: 'AC12', perf: true, note: 'the internal host name rule reads the scheme as a run from every word boundary, as in round 6', f: sub("['internal host name', '://', /[a-z0-9+.-]:\\/\\/[a-z0-9-]+", "['internal host name', '://', /\\b[a-z][a-z0-9+.-]*:\\/\\/[a-z0-9-]+") },
  { id: 'AC12-r7-budget-not-enforced', ac: 'AC12', perf: true, note: 'a string past the scan budget is still read', f: sub('    if (scan.left < 0) return WITHHELD;\n', '') },
  { id: 'AC12-r7-budget-huge', ac: 'AC12', perf: true, note: 'the scan budget is a hundred million characters (no bound in practice)', f: sub('entityChars: 100000,', 'entityChars: 100000000,') },
  { id: 'AC12-r7-budget-halved', ac: 'AC12', note: 'the scan budget is 50000 characters', f: sub('entityChars: 100000,', 'entityChars: 50000,') },
  { id: 'AC12-r7-budget-tiny', ac: 'AC12', note: 'the scan budget is 1000 characters (an honest entity is cut)', f: sub('entityChars: 100000,', 'entityChars: 1000,') },
  { id: 'AC12-r7-key-not-charged', ac: 'AC12', perf: true, note: 'reading a key name costs nothing (200 keys of 20000 characters are free)', f: sub('    ctx.scan.left -= Math.min(String(key).length, LIMITS.scanBound);\n', '') },
  { id: 'AC12-r7-key-name-scan-not-charged', ac: 'AC12', note: 'the scan of a key NAME for secrets costs nothing', f: sub('    ctx.scan.left -= Math.min(k.length, 200);\n', '') },
  { id: 'AC12-r7-key-cache-dropped', ac: 'AC12', perf: true, note: 'a key is read again for every value under it (a list of 200 items under one long key)', f: sub('    ctx.keys.set(key, info);\n', '') },
  { id: 'AC12-r7-key-read-after-exhaustion', ac: 'AC12', note: 'a key name is still read and shown after the budget is gone', f: sub('    if (ctx.scan.left <= 0) {\n      ctx.keyCount += 1;', '    if (false) {\n      ctx.keyCount += 1;') },
  { id: 'AC12-r7-key-unread-remembered', ac: 'AC12', note: 'a key the budget could not pay for is remembered as secret (the next export row, with a fresh budget, withholds it too)', f: sub('    if (ctx.scan.left < 0) return KEY_UNREAD;', '    if (ctx.scan.left < 0) { ctx.keys.set(key, KEY_UNREAD); return KEY_UNREAD; }') },
  { id: 'AC12-r7-export-shares-budget', ac: 'AC12', note: 'every row of an export draws on one budget', f: sub(', { eachItem: true })', ')') },
  { id: 'AC12-r7-state-own-budget', ac: 'AC12', note: 'the attributes, the state, the unit and the name of an entity each have a budget of their own', f: sub('const opts = { extraKeyPatterns: cat.extraPatterns, scan: newScan(), work };', 'const opts = { extraKeyPatterns: cat.extraPatterns, work };') },
  { id: 'AC12-r7-budget-note-dropped', ac: 'AC12', note: 'an entity cut by the budget does not say so', f: sub('if (opts.scan.left < 0) rows.push(attrRow(', 'if (false) rows.push(attrRow(') },
  { id: 'AC12-r7-budget-per-string-not-total', ac: 'AC12', note: 'the budget is reset for every string (a limit per string, not per entity)', f: sub('    scan.left -= t.length;\n', '    scan.left = LIMITS.entityChars - t.length;\n') },
  // ---- review round 7: the chunk class (reviewer mutants N30 to N33 inside valueReason, and the substring forms of the round-6 chunk mutants)
  { id: 'AC10-r7-N30-vr-prefix-3000', ac: 'AC10', note: 'N30: valueReason reads the first 3000 characters of its text', f: sub('function valueReason(raw, digestOk, digestKey = false) {\n  if (raw.length < 6) return null;', 'function valueReason(raw, digestOk, digestKey = false) {\n  if (raw.length < 6) return null;\n  if (raw.length > 3000) raw = raw.substring(0, 3000);') },
  { id: 'AC10-r7-N31-vr-chunks-3000-overlap-200', ac: 'AC10', note: 'N31: valueReason reads chunks of 3000 characters that overlap by 200', f: sub('function valueReason(raw, digestOk, digestKey = false) {\n  if (raw.length < 6) return null;', 'function valueReason(raw, digestOk, digestKey = false) {\n  if (raw.length < 6) return null;\n  if (raw.length > 3000) { for (let i = 0; i < raw.length; i += 2800) { const r = valueReason(raw.substring(i, i + 3000), digestOk, digestKey); if (r !== null) return r; } return null; }') },
  { id: 'AC10-r7-N32-vr-chunks-1024-overlap-128', ac: 'AC10', note: 'N32: valueReason reads chunks of 1024 characters that overlap by 128', f: sub('function valueReason(raw, digestOk, digestKey = false) {\n  if (raw.length < 6) return null;', 'function valueReason(raw, digestOk, digestKey = false) {\n  if (raw.length < 6) return null;\n  if (raw.length > 1024) { for (let i = 0; i < raw.length; i += 896) { const r = valueReason(raw.substring(i, i + 1024), digestOk, digestKey); if (r !== null) return r; } return null; }') },
  { id: 'AC10-r7-N33-vr-chunks-4000-overlap-400', ac: 'AC10', note: 'N33: valueReason reads chunks of 4000 characters that overlap by 400', f: sub('function valueReason(raw, digestOk, digestKey = false) {\n  if (raw.length < 6) return null;', 'function valueReason(raw, digestOk, digestKey = false) {\n  if (raw.length < 6) return null;\n  if (raw.length > 4000) { for (let i = 0; i < raw.length; i += 3600) { const r = valueReason(raw.substring(i, i + 4000), digestOk, digestKey); if (r !== null) return r; } return null; }') },
  { id: 'AC10-r7-vr-chunks-500-overlap-100', ac: 'AC10', note: 'valueReason reads chunks of 500 characters that overlap by 100', f: sub('function valueReason(raw, digestOk, digestKey = false) {\n  if (raw.length < 6) return null;', 'function valueReason(raw, digestOk, digestKey = false) {\n  if (raw.length < 6) return null;\n  if (raw.length > 500) { for (let i = 0; i < raw.length; i += 400) { const r = valueReason(raw.substring(i, i + 500), digestOk, digestKey); if (r !== null) return r; } return null; }') },
  { id: 'AC10-r7-vr-chunks-2048-overlap-256', ac: 'AC10', note: 'valueReason reads chunks of 2048 characters that overlap by 256', f: sub('function valueReason(raw, digestOk, digestKey = false) {\n  if (raw.length < 6) return null;', 'function valueReason(raw, digestOk, digestKey = false) {\n  if (raw.length < 6) return null;\n  if (raw.length > 2048) { for (let i = 0; i < raw.length; i += 1792) { const r = valueReason(raw.slice(i, i + 2048), digestOk, digestKey); if (r !== null) return r; } return null; }') },
  { id: 'AC10-r7-vr-chunks-8192-overlap-1024', ac: 'AC10', note: 'valueReason reads chunks of 8192 characters that overlap by 1024', f: sub('function valueReason(raw, digestOk, digestKey = false) {\n  if (raw.length < 6) return null;', 'function valueReason(raw, digestOk, digestKey = false) {\n  if (raw.length < 6) return null;\n  if (raw.length > 8192) { for (let i = 0; i < raw.length; i += 7168) { const r = valueReason(raw.substring(i, i + 8192), digestOk, digestKey); if (r !== null) return r; } return null; }') },
  { id: 'AC10-r7-vr-chunks-12000-overlap-2500', ac: 'AC10', note: 'valueReason reads chunks of 12000 characters that overlap by 2500 (shorter than the longest kind, 3033)', f: sub('function valueReason(raw, digestOk, digestKey = false) {\n  if (raw.length < 6) return null;', 'function valueReason(raw, digestOk, digestKey = false) {\n  if (raw.length < 6) return null;\n  if (raw.length > 12000) { for (let i = 0; i < raw.length; i += 9500) { const r = valueReason(raw.substring(i, i + 12000), digestOk, digestKey); if (r !== null) return r; } return null; }') },
  { id: 'AC10-r7-N02b-substring-chunks-3000-overlap-200', ac: 'AC10', note: 'N02b: the text is read in chunks of 3000 characters that overlap by 200, cut with substring', f: sub(SCAN_LINE, '  { let hit = false; for (let i = 0; i < t.length; i += 2800) if (valueReason(t.substring(i, i + 3000), digestOk, digestKey) !== null) hit = true; if (hit) return WITHHELD; }') },
  { id: 'AC10-r7-N03b-substring-chunks-2000-overlap-100', ac: 'AC10', note: 'N03b: chunks of 2000 characters that overlap by 100', f: sub(SCAN_LINE, '  { let hit = false; for (let i = 0; i < t.length; i += 1900) if (valueReason(t.substring(i, i + 2000), digestOk, digestKey) !== null) hit = true; if (hit) return WITHHELD; }') },
  { id: 'AC10-r7-N09b-substring-chunks-4096-overlap-64', ac: 'AC10', note: 'N09b: chunks of 4096 characters that overlap by 64', f: sub(SCAN_LINE, '  { let hit = false; for (let i = 0; i < t.length; i += 4032) if (valueReason(t.substring(i, i + 4096), digestOk, digestKey) !== null) hit = true; if (hit) return WITHHELD; }') },
  { id: 'AC10-r7-N29-substring-chunks-1500-overlap-300', ac: 'AC10', note: 'N29: chunks of 1500 characters that overlap by 300', f: sub(SCAN_LINE, '  { let hit = false; for (let i = 0; i < t.length; i += 1200) if (valueReason(t.substring(i, i + 1500), digestOk, digestKey) !== null) hit = true; if (hit) return WITHHELD; }') },
  { id: 'AC10-r7-redactnode-substring', ac: 'AC10', note: 'redactNode hands only the first 5000 characters of a string to the redactor', f: sub("  if (t === 'string') return redactString(v,", "  if (t === 'string') return redactString(v.length > 5000 ? v.substring(0, 5000) : v,") },
  { id: 'AC10-r7-keyinfo-key-cut', ac: 'AC10', note: 'keyInfo reads only the first 50 characters of a key name', f: sub('    const secret = isSecretKey(key, ctx.extra);', '    const secret = isSecretKey(String(key).slice(0, 50), ctx.extra);') },
  // ---- review round 7: the key-fold class (reviewer mutant N13) and the key words (the NIT)
  { id: 'AC10-r7-N13-key-not-folded', ac: 'AC10', note: 'N13: the catalogue fragments are matched on the key as written, not folded (a zero-width character, a Cyrillic o or a fullwidth s hides the key)', f: sub('keyHasFragment(fold(String(key)), extra) ||', 'keyHasFragment(String(key), extra) ||') },
  { id: 'AC10-r7-keytokens-not-folded', ac: 'AC10', note: 'the words of a key are made from the key as written (a look-alike letter or a zero-width character splits a secret word)', f: sub('fold(String(key)).replace(/([a-z0-9])([A-Z])/g,', 'String(key).replace(/([a-z0-9])([A-Z])/g,') },
  { id: 'AC10-r7-fragment-words-dropped', ac: 'AC10', note: 'the NIT: a fragment is not looked for in the key\'s words (site-owner, "site owner", siteOwner are shown)', f: sub(" || keyHasFragment(tokens.join('_'), extra);", ';') },
  { id: 'AC10-r7-fragment-words-joined-bare', ac: 'AC10', note: 'the key\'s words are joined with nothing between them (site_owner is not found in site-owner)', f: sub("keyHasFragment(tokens.join('_'), extra)", "keyHasFragment(tokens.join(''), extra)") },
  { id: 'AC10-r7-fragment-words-joined-space', ac: 'AC10', note: 'the key\'s words are joined with a space', f: sub("keyHasFragment(tokens.join('_'), extra)", "keyHasFragment(tokens.join(' '), extra)") },
  // ---- review round 7: the Web Animations API and the dynamic stylesheet APIs (reviewer mutant N21: the strip is hidden by an animation that fills forwards). `browser: true`: the headless check is asked too
  { id: 'AC6-r7-N21-animate-strip', ac: 'AC6', browser: true, note: 'N21: Geek Mode hides the alert strip with an animation that fills forwards (the Web Animations API)', f: sub(GEEK_LINE, `${GEEK_LINE}\n    if (mode === 'geek' && typeof ui.strip.animate === 'function') ui.strip.animate([{ opacity: 0 }, { opacity: 0 }], { duration: 1e9, fill: 'forwards' });`) },
  { id: 'AC6-r7-getanimations', ac: 'AC6', note: 'Geek Mode pauses the animations of the strip', f: sub(GEEK_LINE, `${GEEK_LINE}\n    if (mode === 'geek' && typeof ui.strip.getAnimations === 'function') for (const a of ui.strip.getAnimations()) a.pause();`) },
  { id: 'AC6-r7-keyframeeffect', ac: 'AC6', note: 'Geek Mode builds a keyframe effect on the strip', f: sub(GEEK_LINE, `${GEEK_LINE}\n    if (mode === 'geek' && typeof KeyframeEffect === 'function') void new KeyframeEffect(ui.strip, [{ opacity: 0 }], 1);`) },
  { id: 'AC6-r7-adopted-stylesheet', ac: 'AC6', note: 'Geek Mode adopts a constructed stylesheet that hides the strip', f: sub(GEEK_LINE, `${GEEK_LINE}\n    if (mode === 'geek' && typeof CSSStyleSheet === 'function') { const sh = new CSSStyleSheet(); sh.replaceSync('[data-ecco-alert-strip]{display:none}'); this.ownerDocument.adoptedStyleSheets = [sh]; }`) },
  { id: 'AC6-r7-insertrule', ac: 'AC6', note: 'Geek Mode inserts a rule into the card\'s style sheet', f: sub(GEEK_LINE, `${GEEK_LINE}\n    if (mode === 'geek' && this._root.firstChild && this._root.firstChild.sheet) this._root.firstChild.sheet.insertRule('[data-ecco-alert-strip]{display:none}');`) },
  { id: 'AC6-r7-second-style-element', ac: 'AC6', note: 'Geek Mode makes a second style element that hides the strip', f: sub(GEEK_LINE, `${GEEK_LINE}\n    if (mode === 'geek') { const st = this.ownerDocument.createElement('style'); st.textContent = '[data-ecco-alert-strip]{display:none}'; this._root.appendChild(st); }`) },
  { id: 'AC6-r7-link-element', ac: 'AC6', note: 'Geek Mode makes a link element', f: sub(GEEK_LINE, `${GEEK_LINE}\n    if (mode === 'geek') { const lk = this.ownerDocument.createElement('link'); lk.setAttribute('rel', 'stylesheet'); this._root.appendChild(lk); }`) },
  { id: 'AC6-r7-computedstylemap', ac: 'AC6', note: 'Geek Mode reads the computed style map of the strip', f: sub(GEEK_LINE, `${GEEK_LINE}\n    if (mode === 'geek') void ui.strip.computedStyleMap;`) },
  // ---- review round 8: the regression class (the rules written back as round 7 had them, with the bounds; `diff: true`: the differential gate is asked, and the bounds test of scan.test.mjs asks too)
  { id: 'AC10-r8-jwt-bounded-as-round-7', ac: 'AC10', diff: true, note: 'the JWT rule is bounded as in round 7 ({4,512} and {4,4096}): a first segment of 600 characters is shown', f: sub('/(?<=\\beyJ[\\w-]{4,}\\.[\\w-]{4,})\\./],', '/\\beyJ[\\w-]{4,512}\\.[\\w-]{4,4096}\\.[\\w-]*/],') },
  { id: 'AC10-r8-jwt-bounded-large', ac: 'AC10', diff: true, note: 'the JWT rule is bounded at 2000 and 8000 characters (a bound larger than anything a source writes is still a hole)', f: sub('/(?<=\\beyJ[\\w-]{4,}\\.[\\w-]{4,})\\./],', '/\\beyJ[\\w-]{4,2000}\\.[\\w-]{4,8000}\\.[\\w-]*/],') },
  { id: 'AC10-r8-key-block-bounded-as-round-7', ac: 'AC10', diff: true, note: 'the key block label is bounded as in round 7 ({1,64}): a label of 80 characters is shown', f: sub('/-----BEGIN [A-Z0-9 ]+-----/],', '/-----BEGIN [A-Z0-9 ]{1,64}-----/],') },
  { id: 'AC10-r8-url-token-bounded-as-round-7', ac: 'AC10', diff: true, note: 'the URL token parameter name is bounded as in round 7 ({0,64} each side): a name of 65 characters shows a real secret value',
    f: sub('/[?&#;](?=[\\w.%-]*=[^&\\s]{3})(?=[\\w.%-]*?(?:token|secret|passw|pwd|apikey|api[_-]?key|auth|sig|signature|credential|session|bearer|jwt|key))/i],',
      '/[?&#;][\\w.%-]{0,64}(?:token|secret|passw|pwd|apikey|api[_-]?key|auth|sig|signature|credential|session|bearer|jwt|key)[\\w.%-]{0,64}=[^&\\s]{3,}/i],') },
  { id: 'AC10-r8-url-token-bounded-large', ac: 'AC10', diff: true, note: 'the URL token parameter name is bounded at 300 characters each side',
    f: sub('/[?&#;](?=[\\w.%-]*=[^&\\s]{3})(?=[\\w.%-]*?(?:token|secret|passw|pwd|apikey|api[_-]?key|auth|sig|signature|credential|session|bearer|jwt|key))/i],',
      '/[?&#;][\\w.%-]{0,300}(?:token|secret|passw|pwd|apikey|api[_-]?key|auth|sig|signature|credential|session|bearer|jwt|key)[\\w.%-]{0,300}=[^&\\s]{3,}/i],') },
  { id: 'AC10-r8-connection-pairs-bounded-as-round-7', ac: 'AC10', diff: true, note: 'the connection pairs rule is bounded as in round 7 (a value of 256 after a boundary, any length only after a space, a semicolon or the start)',
    f: sub('/(?<=\\b(?:server|data source|host|hostname|uid|user ?id|userid|pwd|password|database|initial catalog)\\s*=\\s*[^;\\s]+\\s*);/i],',
      '/\\b(?:server|data source|host|hostname|uid|user ?id|userid|pwd|password|database|initial catalog)\\s*=\\s*[^;\\s]{1,256}\\s*;|(?:^|[;\\s])(?:server|data source|host|hostname|uid|user ?id|userid|pwd|password|database|initial catalog)\\s*=\\s*[^;\\s]+\\s*;/i],') },
  { id: 'AC10-r8-connection-pairs-key-after-space-only', ac: 'AC10', diff: true, note: 'the connection pairs rule needs the key at the start, after a space or after a semicolon (a bracket, a comma or a quote before the key hides the pair)',
    f: sub('/(?<=\\b(?:server|data source|host|hostname|uid|user ?id|userid|pwd|password|database|initial catalog)\\s*=\\s*[^;\\s]+\\s*);/i],',
      '/(?<=(?:^|[;\\s])(?:server|data source|host|hostname|uid|user ?id|userid|pwd|password|database|initial catalog)\\s*=\\s*[^;\\s]+\\s*);/i],') },
  { id: 'AC10-r8-webhook-host-bounded-as-round-7', ac: 'AC10', diff: true, note: 'the chat services webhook host is bounded as in round 7 ({1,253})', f: sub('(?<=hooks\\.[a-z0-9.-]+)\\/services\\/', 'hooks\\.[a-z0-9.-]{1,253}\\/services\\/') },
  { id: 'AC10-r8-mac-dotted-narrowed-as-round-7', ac: 'AC10', diff: true, note: 'the dotted MAC rule looks for the letter in the fourteen characters only (2026.1114.0900.beef is shown)',
    f: sub('|[a-f](?![0-9a-f.]*?[a-f])(?<=\\b[0-9a-f]{4}\\.[0-9a-f]{4}\\.[0-9a-f]{4}\\b[0-9a-f.]*[a-f])/i],', '/i],') },
  // ---- review round 8: the rules written back as round 6 had them (exact, and quadratic on near-miss text: `perf: true`)
  { id: 'AC12-r8-url-token-round-6-form', ac: 'AC12', perf: true, note: 'the URL token rule is the round-6 form (names of any length walked from every separator: quadratic on ?tokentoken...)',
    f: sub('/[?&#;](?=[\\w.%-]*=[^&\\s]{3})(?=[\\w.%-]*?(?:token|secret|passw|pwd|apikey|api[_-]?key|auth|sig|signature|credential|session|bearer|jwt|key))/i],',
      '/[?&#;][\\w.%-]*(?:token|secret|passw|pwd|apikey|api[_-]?key|auth|sig|signature|credential|session|bearer|jwt|key)[\\w.%-]*=[^&\\s]{3,}/i],') },
  { id: 'AC12-r8-connection-pairs-round-6-form', ac: 'AC12', perf: true, note: 'the connection pairs rule is the round-6 form (host=host=host=... is quadratic)',
    f: sub('/(?<=\\b(?:server|data source|host|hostname|uid|user ?id|userid|pwd|password|database|initial catalog)\\s*=\\s*[^;\\s]+\\s*);/i],',
      '/\\b(?:server|data source|host|hostname|uid|user ?id|userid|pwd|password|database|initial catalog)\\s*=\\s*[^;\\s]+\\s*;/i],') },
  { id: 'AC12-r8-jwt-round-6-form', ac: 'AC12', perf: true, note: 'the JWT rule is the round-6 form (eyJ-eyJ-eyJ-... is quadratic)', f: sub('/(?<=\\beyJ[\\w-]{4,}\\.[\\w-]{4,})\\./],', '/\\beyJ[\\w-]{4,}\\.[\\w-]{4,}\\.[\\w-]*/],') },
  { id: 'AC12-r8-webhook-round-6-form', ac: 'AC12', perf: true, note: 'the webhook rule is the round-6 form (hooks.hooks.hooks... is quadratic)', f: sub('(?<=hooks\\.[a-z0-9.-]+)\\/services\\/', 'hooks\\.[a-z0-9.-]+\\/services\\/') },
  { id: 'AC12-r8-mac-dotted-round-6-form', ac: 'AC12', perf: true, note: 'the dotted MAC rule is the round-6 form (a look-ahead to the end of the dotted text from every start)',
    f: sub('/\\b(?=[0-9a-f.]{0,13}[a-f])[0-9a-f]{4}\\.[0-9a-f]{4}\\.[0-9a-f]{4}\\b|[a-f](?![0-9a-f.]*?[a-f])(?<=\\b[0-9a-f]{4}\\.[0-9a-f]{4}\\.[0-9a-f]{4}\\b[0-9a-f.]*[a-f])/i],', '/\\b(?=[0-9a-f.]*[a-f])[0-9a-f]{4}\\.[0-9a-f]{4}\\.[0-9a-f]{4}\\b/i],') },
  { id: 'AC12-r8-mac-dotted-eager-lookahead', ac: 'AC12', perf: true, note: 'the second alternative of the dotted MAC rule looks ahead greedily (a text of letters is walked from every letter)', f: sub('[a-f](?![0-9a-f.]*?[a-f])(?<=', '[a-f](?![0-9a-f.]*[a-f])(?<=') },
  // ---- review round 8: KEY UNREAD (reviewer mutant M14) and the snapshot budget (budget.test.mjs, perf.test.mjs)
  { id: 'AC10-r8-M14-key-unread-not-secret', ac: 'AC10', note: 'M14: a key the budget could not pay for is not treated as secret (every number and boolean under it is shown)', f: sub('const KEY_UNREAD = Object.freeze({ secret: true, digest: false });', 'const KEY_UNREAD = Object.freeze({ secret: false, digest: false });') },
  { id: 'AC10-r8-key-unread-strings-only', ac: 'AC10', note: 'a key the budget could not pay for withholds a string but shows a number, a boolean, a list and a dict', f: sub('    if (info.secret) return WITHHELD;\n  }\n  const t = typeof v;', "    if (info.secret && (typeof v === 'string' || info === KEY_UNREAD && typeof v === 'string')) return WITHHELD;\n  }\n  const t = typeof v;") },
  { id: 'AC12-r8-snapshot-budget-not-spent', ac: 'AC12', note: 'the snapshot budget is never charged (every entity is read)', f: sub('    budget.left -= row.spent;\n', '') },
  { id: 'AC12-r8-snapshot-budget-ignored', ac: 'AC12', note: 'the decision to read ignores the budget', f: sub('isObj(state) && budget.left <= 0)', 'false)') },
  { id: 'AC12-r8-snapshot-budget-one-more', ac: 'AC12', note: 'one entity more than the budget pays for is read', f: sub('isObj(state) && budget.left <= 0)', 'isObj(state) && budget.left <= -LIMITS.entityChars)') },
  { id: 'AC12-r8-snapshot-budget-huge', ac: 'AC12', perf: true, note: 'the snapshot budget is a hundred million characters (no bound in practice)', f: sub('snapshotChars: 2000000,', 'snapshotChars: 100000000,') },
  { id: 'AC12-r8-snapshot-budget-tenfold', ac: 'AC12', perf: true, note: 'the snapshot budget is twenty million characters', f: sub('snapshotChars: 2000000,', 'snapshotChars: 20000000,') },
  { id: 'AC12-r8-order-not-ranked', ac: 'AC12', note: 'the entities are read in catalogue order, not alert-bearing first', f: sub('  jobs.sort((a, b) => a.rank - b.rank || a.order - b.order);', '  jobs.sort((a, b) => a.order - b.order);') },
  { id: 'AC12-r8-alert-rank-dropped', ac: 'AC12', note: 'an entity an alert watches is read like any other source', f: sub("rank: cat.alertIds.has(src.entity_id) ? 0 : src.priority === 'headline' ? 1 : 2,", "rank: src.priority === 'headline' ? 1 : 2,") },
  { id: 'AC12-r8-headline-rank-dropped', ac: 'AC12', note: 'a headline source is read like any other source', f: sub("rank: cat.alertIds.has(src.entity_id) ? 0 : src.priority === 'headline' ? 1 : 2,", 'rank: cat.alertIds.has(src.entity_id) ? 0 : 2,') },
  { id: 'AC12-r8-discovered-first', ac: 'AC12', note: 'the discovered entities are read before the catalogue sources', f: sub('rank: cat.alertIds.has(id) ? 0 : 3,', 'rank: cat.alertIds.has(id) ? 0 : -1,') },
  { id: 'AC12-r8-unread-through-the-cache', ac: 'AC12', note: 'an entity that is not to be read is given a row through the cache (it is read, or a cached row is shown)', f: sub('  if (unread) return buildRow(source, state, nowMs, cat, order, ledgerKey, true);\n', '') },
  { id: 'AC12-r8-unread-keeps-parts', ac: 'AC12', note: 'an entity that was not read still has its parts built (it is scanned and its text is in the row)', f: sub('const parts = present && !unreadHere ? partsFor(source, state, cat) : null;', 'const parts = present ? partsFor(source, state, cat) : null;') },
  { id: 'AC12-r8-unread-state-shown', ac: 'AC12', note: 'the state of an entity that was not read is shown as it is', f: sub('else stateText = unreadHere ? WITHHELD : parts.stateStr;', 'else stateText = unreadHere ? String(state.state) : parts.stateStr;') },
  { id: 'AC12-r8-unread-no-note', ac: 'AC12', note: 'an entity that was not read does not say so in its attribute list', f: sub("if (unreadHere) attributes = [attrRow('\\u2026', '\\u2026 values not read', null, 0, null, true, UNREAD_NOTE)];", 'if (unreadHere) attributes = [];') },
  { id: 'AC12-r8-unread-not-a-problem', ac: 'AC12', note: 'an entity that was not read is not a problem row', f: sub("problem: cls.status !== 'LIVE' || unreadHere,", "problem: cls.status !== 'LIVE',") },
  { id: 'AC12-r8-unread-not-counted', ac: 'AC12', note: 'the count of entities that were not read is dropped', f: sub('    if (r.unread) counts.unread += 1;\n', '') },
  { id: 'AC12-r8-summary-silent', ac: 'AC12', note: 'Production does not say that data points were not read', f: sub("  if (unread > 0) notes.push(", "  if (false) notes.push(") },
  { id: 'AC12-r8-spent-zero', ac: 'AC12', note: 'a row carries no cost (the budget is never charged)', f: sub('order, unread: unreadHere, spent: parts ? parts.spent : 0,', 'order, unread: unreadHere, spent: 0,') },
  { id: 'AC12-r8-nodes-not-charged', ac: 'AC12', note: 'the values an entity visited are not charged (twenty thousand numbers cost nothing)', f: sub(' + work.nodes * LIMITS.nodeChars);', ');') },
  { id: 'AC12-r8-base-cost-dropped', ac: 'AC12', note: 'an entity costs only what it read (a tiny entity is free)', f: sub('const spent = Math.max(LIMITS.entityBaseChars, Math.min(', 'const spent = Math.max(0, Math.min(') },
  { id: 'AC12-r8-cost-uncapped', ac: 'AC12', note: 'the cost of an entity is not capped at its own budget (a read that overshoots is charged in full)', f: sub('Math.min(LIMITS.entityChars, LIMITS.entityChars - opts.scan.left)', '(LIMITS.entityChars - opts.scan.left)') },
  { id: 'AC12-r8-charge-order-attributes-first', ac: 'AC12', note: 'the attributes are charged and read before the state, the name and the unit (round 7: the headline of an over-budget entity is withheld)',
    f: chain(sub('  const red = redactAttributes(attrsRaw, opts);\n  const declared', '  const declared'), sub('  const stateRed = redactValue(stateStr, opts);\n', '  const red = redactAttributes(attrsRaw, opts);\n  const stateRed = redactValue(stateStr, opts);\n')) },
  { id: 'AC12-r8-charge-order-name-last', ac: 'AC12', note: 'the name and the unit are charged after the attributes', f: chain(sub("  const friendly = isStr(attrsRaw.friendly_name) ? redactValue(attrsRaw.friendly_name, { ...opts, key: 'note' }) : '';\n", ''), sub("  const unitRaw = isStr(attrsRaw.unit_of_measurement) ? redactValue(attrsRaw.unit_of_measurement, opts) : '';\n  const red = redactAttributes(attrsRaw, opts);\n", "  const unitRaw = isStr(attrsRaw.unit_of_measurement) ? redactValue(attrsRaw.unit_of_measurement, opts) : '';\n  const red = redactAttributes(attrsRaw, opts);\n  const friendly = isStr(attrsRaw.friendly_name) ? redactValue(attrsRaw.friendly_name, { ...opts, key: 'note' }) : '';\n")) },
  { id: 'AC12-r8-id-length-uncapped', ac: 'AC12', note: 'an id of any length is read (and a long one that no rule objects to is shown)', f: sub('const display = job.id.length > LIMITS.entityIdChars ? WITHHELD : redactString(job.id, \'note\');', "const display = redactString(job.id, 'note');") },
  // ---- review round 8: the tripwires (reviewer mutants M38, M39, M40, M40b): the member is reached by a name made of pieces, by a computed key, by the prototype chain
  { id: 'AC12-r8-header-count-dropped', ac: 'AC12', note: 'the Geek header does not say how many data points were not read', f: sub("${c.unread ? ` \\u00b7 ${c.unread} not read (too much data for one pass)` : ''}", '') },
  { id: 'AC6-r8-M38-animate-bracket-concat', ac: 'AC6', browser: true, note: 'M38: Geek Mode hides the strip with the animation API reached by a name built from pieces (const fn = ani + mate; strip[fn](...))', f: sub(GEEK_LINE, `${GEEK_LINE}\n    { const fn = 'ani' + 'mate'; if (mode === 'geek' && typeof ui.strip[fn] === 'function') ui.strip[fn]([{ opacity: 0 }, { opacity: 0 }], { duration: 1e9, fill: 'forwards' }); }`) },
  { id: 'AC6-r8-M39-attribute-style-map', ac: 'AC6', note: 'M39: Geek Mode sets the opacity of the strip through its typed style map', f: sub(GEEK_LINE, `${GEEK_LINE}\n    if (mode === 'geek' && ui.strip.attributeStyleMap) ui.strip.attributeStyleMap.set('opacity', 0);`) },
  { id: 'AC6-r8-M40-prototype-call', ac: 'AC6', note: 'M40: Geek Mode finds animate on the grandparent prototype of the strip and calls it (in a real browser animate lives one level higher, on Element.prototype, so this one hides nothing there: the headless check passes it, and the node suites alone kill it)', f: sub(GEEK_LINE, `${GEEK_LINE}\n    { const P = Object.getPrototypeOf(Object.getPrototypeOf(ui.strip)); const k = Object.getOwnPropertyNames(P).find((n) => n.length === 7 && n.startsWith('anim')); if (mode === 'geek' && k) P[k].call(ui.strip, [{ opacity: 0 }, { opacity: 0 }], { duration: 1e9, fill: 'forwards' }); }`) },
  { id: 'AC6-r8-M40b-prototype-walk-animate', ac: 'AC6', browser: true, note: 'M40b: Geek Mode walks the whole prototype chain of the strip, finds animate and calls it', f: sub(GEEK_LINE, `${GEEK_LINE}\n    { let P = ui.strip; let k; while (P && !k) { P = Object.getPrototypeOf(P); if (P) k = Object.getOwnPropertyNames(P).find((n) => n.length === 7 && n.startsWith('anim')); } if (mode === 'geek' && k) P[k].call(ui.strip, [{ opacity: 0 }, { opacity: 0 }], { duration: 1e9, fill: 'forwards' }); }`) },
  { id: 'AC6-r8-computed-key-getanimations', ac: 'AC6', note: 'Geek Mode pauses the animations of the strip through a key held in a variable', f: sub(GEEK_LINE, `${GEEK_LINE}\n    { const k = mode === 'geek' ? 'getAnimations' : 'x'; if (typeof ui.strip[k] === 'function') for (const a of ui.strip[k]()) a.pause(); }`) },
  { id: 'AC6-r8-computed-key-sheet', ac: 'AC6', note: 'Geek Mode inserts a rule into a stylesheet reached through a key held in a variable', f: sub(GEEK_LINE, `${GEEK_LINE}\n    { const k = 'sh' + 'eet'; if (mode === 'geek' && this._root.firstChild && this._root.firstChild[k]) this._root.firstChild[k].insertRule('[data-ecco-alert-strip]{display:none}'); }`) },
  { id: 'AC6-r8-computed-key-adopted', ac: 'AC6', note: 'Geek Mode adopts a stylesheet reached through a key held in a variable', f: sub(GEEK_LINE, `${GEEK_LINE}\n    { const k = ['adopted', 'Style', 'Sheets'].join(''); if (mode === 'geek') this.ownerDocument[k] = []; }`) },
  { id: 'AC6-r8-string-key-animate', ac: 'AC6', note: 'Geek Mode calls animate through a quoted bracket key', f: sub(GEEK_LINE, `${GEEK_LINE}\n    if (mode === 'geek' && typeof ui.strip['animate'] === 'function') ui.strip['animate']([{ opacity: 0 }, { opacity: 0 }], { duration: 1e9, fill: 'forwards' });`) },
  // ---- review round 9 (design section 21). THE ASYNC-HIDE CLASS (reviewer mutants E05, E07, E08, and the same hide by every other way of deferring work: a microtask, a timer of any delay, an animation frame, an idle callback, an observer callback, a listener, a chain of them, a hide inside
  // an allowed site). Each is killed by test/async.test.mjs (the pin of the places where the card may defer work), by the scheduler of test/async-net.mjs (element.test.mjs: every AC6 test settles after each step, the afterEach does it for every test, and THE TOUR runs everything that is
  // scheduled after every step of a session), or by both. `browser: true`: the headless check also measures after a zero-delay timer and two animation frames. THE CACHE CLASS (B11 and its variants, every cache of the card returning a stale, free or wrong-key result): killed by
  // cache.test.mjs, which compares the snapshot from warm caches with a cold read after every step of a history, and by the Geek surface test of element.test.mjs. THE HONESTY FIX (H): the problem sentence of Production counts the rows whose status is not live, read or not.
  { id: 'AC6-r9-E04-queuemicrotask-hide', ac: 'AC6', note: 'a microtask hides the strip after the switch to Geek Mode', f: gl9("    queueMicrotask(() => { ui.strip.hidden = mode === 'geek'; });") },
  { id: 'AC6-r9-E05-promise-then-clear', ac: 'AC6', browser: true, note: 'E05 (reviewer, round 9): a promise continuation empties the strip text one tick after the switch to Geek Mode', f: gl9("    Promise.resolve().then(() => { if (mode === 'geek') ui.strip.textContent = ''; });") },
  { id: 'AC6-r9-E05b-promise-then-hidden', ac: 'AC6', note: 'a promise continuation hides the strip after the switch', f: gl9("    Promise.resolve().then(() => { ui.strip.hidden = mode === 'geek'; });") },
  { id: 'AC6-r9-E05c-promise-then-aria-hidden', ac: 'AC6', note: 'a promise continuation sets aria-hidden on the strip after the switch', f: gl9("    Promise.resolve().then(() => { if (mode === 'geek') ui.strip.setAttribute('aria-hidden', 'true'); });") },
  { id: 'AC6-r9-E07-render-strip-async-clear-in-geek', ac: 'AC6', browser: true, note: 'E07 (reviewer, round 9): the renderer empties the strip in a promise continuation, after every render, while in Geek Mode', f: sub(RENDER_END9, "  strip.replaceChildren(...kids);\n  Promise.resolve().then(() => { const s = strip.closest('[data-mode]'); if (s && s.getAttribute('data-mode') === 'geek') strip.replaceChildren(); });\n}") },
  { id: 'AC6-r9-E08-applymode-async-fn', ac: 'AC6', browser: true, note: 'E08 (reviewer, round 9): an async function awaits and then empties the strip after the switch (it survived at one process at a time, and was "killed" only by a timing test under load)', f: gl9("    (async () => { await null; if (mode === 'geek') ui.strip.replaceChildren(); })();") },
  { id: 'AC6-r9-E09-settimeout-0-hide', ac: 'AC6', browser: true, note: 'a timer of zero hides the strip after the switch', f: gl9("    setTimeout(() => { ui.strip.hidden = mode === 'geek'; }, 0);") },
  { id: 'AC6-r9-E10-settimeout-20s-clear', ac: 'AC6', note: 'a timer of twenty seconds empties the strip (the scheduler runs timers of any delay)', f: gl9("    setTimeout(() => { if (this._ctl.mode === 'geek') ui.strip.replaceChildren(); }, 20000);") },
  { id: 'AC6-r9-E11-second-interval-hide', ac: 'AC6', note: 'a second interval hides the strip in Geek Mode', f: gl9("    setInterval(() => { if (this._ctl.mode === 'geek') ui.strip.hidden = true; }, 15000);") },
  { id: 'AC6-r9-E12-raf-guarded-hide', ac: 'AC6', note: 'an animation frame hides the strip (behind a typeof test: dormant in Node without the scheduler of async-net.mjs)', f: gl9("    if (typeof requestAnimationFrame === 'function') requestAnimationFrame(() => { if (this._ctl.mode === 'geek') ui.strip.hidden = true; });") },
  { id: 'AC6-r9-E13-ric-guarded-hide', ac: 'AC6', note: 'an idle callback hides the strip (behind a typeof test)', f: gl9("    if (typeof requestIdleCallback === 'function') requestIdleCallback(() => { if (this._ctl.mode === 'geek') ui.strip.hidden = true; });") },
  { id: 'AC6-r9-E14-mutationobserver-guarded-clear', ac: 'AC6', browser: true, note: 'a mutation observer empties the strip (behind a typeof test)', f: gl9("    if (typeof MutationObserver === 'function' && mode === 'geek') new MutationObserver(() => { ui.strip.replaceChildren(); }).observe(ui.shell, { childList: true, subtree: true });") },
  { id: 'AC6-r9-E15-intersectionobserver-guarded-hide', ac: 'AC6', note: 'an intersection observer hides the strip when it reports the strip as not visible (behind a typeof test)', f: gl9("    if (typeof IntersectionObserver === 'function' && mode === 'geek') new IntersectionObserver((entries) => { if (entries.some((e) => !e.isIntersecting)) ui.strip.hidden = true; }).observe(ui.strip);") },
  { id: 'AC6-r9-E16-resizeobserver-callback-hide', ac: 'AC6', note: 'the resize observer callback (an allowed site) also hides the strip on a normal box in Geek Mode', f: sub('if (r && r.width === 0 && r.height === 0) this._ctl.reset();', `if (r && r.width === 0 && r.height === 0) this._ctl.reset();\n          else if (r && r.width > 0 && ${IS_GEEK9}) this._ui.strip.hidden = true;`) },
  { id: 'AC6-r9-E17-listener-on-strip-hide', ac: 'AC6', note: 'a click listener on the strip hides it in Geek Mode', f: gl9("    ui.strip.addEventListener('click', () => { if (this._ctl.mode === 'geek') ui.strip.hidden = true; });") },
  { id: 'AC6-r9-E18-listener-on-window-clear', ac: 'AC6', note: 'a focus listener on the window empties the strip in Geek Mode', f: gl9("    window.addEventListener('focus', () => { if (this._ctl.mode === 'geek') ui.strip.replaceChildren(); });") },
  { id: 'AC6-r9-E19-window-computed-timeout', ac: 'AC6', note: 'a timer reached through window[name] with the name built from pieces hides the strip (no reader of the source can follow it; the scheduler records it)', f: gl9("    { const k = 'set' + 'Timeout'; if (mode === 'geek' && typeof window[k] === 'function') window[k](() => { ui.strip.hidden = true; }, 0); }") },
  { id: 'AC6-r9-E20-fourth-render-clears-in-geek', ac: 'AC6', note: 'the fourth render in Geek Mode empties the strip (state that builds up: only a test that renders several times sees it)', f: sub(RENDER_END9, "  strip.replaceChildren(...kids);\n  strip.renders = (strip.renders || 0) + 1;\n  const sh = strip.closest('[data-mode]');\n  if (strip.renders > 3 && sh && sh.getAttribute('data-mode') === 'geek') strip.replaceChildren();\n}") },
  { id: 'AC6-r9-E21-timer-path-hide', ac: 'AC6', note: 'the timer path hides the strip in Geek Mode, in the task of the tick', f: sub('    if (this._timerMs !== TICK_MS) this._startTimer(TICK_MS);\n    this._tick();\n  }', `    if (this._timerMs !== TICK_MS) this._startTimer(TICK_MS);\n    this._tick();\n    if (${IS_GEEK9}) this._ui.strip.hidden = true;\n  }`) },
  { id: 'AC6-r9-E22-helpers-then-clears-strip', ac: 'AC6', note: 'the card-helpers continuation (an allowed site) also empties the strip in Geek Mode', f: sub('helpers().then((hp) => attach(hp.createCardElement(cfg)))', `helpers().then((hp) => { attach(hp.createCardElement(cfg)); if (${IS_GEEK9}) this._ui.strip.replaceChildren(); })`) },
  { id: 'AC6-r9-E23-clipboard-then-clears-strip', ac: 'AC6', note: 'the clipboard continuation (an allowed site) also empties the strip in Geek Mode', f: sub('    clip.writeText(text).then(() => say(', `    clip.writeText(text).then(() => { if (${IS_GEEK9}) this._ui.strip.replaceChildren(); }).then(() => say(`) },
  { id: 'AC6-r9-E24-deferred-empty-render-in-geek', ac: 'AC6', note: 'a promise continuation after each refresh re-renders the strip with no alerts in Geek Mode', f: sub('    renderAlertStrip(this.ownerDocument, ui.strip, this._alerts);\n    const sum', "    renderAlertStrip(this.ownerDocument, ui.strip, this._alerts);\n    Promise.resolve().then(() => { if (this._ctl.mode === 'geek') renderAlertStrip(this.ownerDocument, ui.strip, []); });\n    const sum") },
  { id: 'AC6-r9-E25-click-handler-microtask-hide', ac: 'AC6', note: 'a microtask queued by the switch click hides the strip', f: sub("on(b, 'click', () => this._ctl.set(mode));", `on(b, 'click', () => { this._ctl.set(mode); queueMicrotask(() => { if (${IS_GEEK9}) this._ui.strip.hidden = true; }); });`) },
  { id: 'AC6-r9-E26-deferred-move-of-strip', ac: 'AC6', note: 'a promise continuation moves the strip to the end of the shell in Geek Mode', f: gl9("    Promise.resolve().then(() => { if (mode === 'geek') ui.shell.appendChild(ui.strip); });") },
  { id: 'AC6-r9-E27-settimeout-aria-hidden', ac: 'AC6', note: 'a timer of zero sets aria-hidden on the strip in Geek Mode', f: gl9("    setTimeout(() => { if (mode === 'geek') ui.strip.setAttribute('aria-hidden', 'true'); }, 0);") },
  { id: 'AC6-r9-E28-hass-setter-microtask-clear', ac: 'AC6', note: 'a microtask after the hass setter empties the strip in Geek Mode', f: sub('    this._syncTheme();\n    this._refresh(false);\n  }', `    this._syncTheme();\n    this._refresh(false);\n    queueMicrotask(() => { if (${IS_GEEK9}) this._ui.strip.replaceChildren(); });\n  }`) },
  { id: 'AC6-r9-E29-timer-microtask-frame-chain', ac: 'AC6', note: 'a timer starts a microtask that starts an animation frame that hides the strip (a chain of three)', f: gl9("    setTimeout(() => queueMicrotask(() => requestAnimationFrame(() => { if (this._ctl.mode === 'geek') ui.strip.hidden = true; })), 10);") },
  { id: 'AC6-r9-E30-age-tick-callback-hides', ac: 'AC6', note: 'the age tick callback (an allowed site) hides the strip in Geek Mode after it has run', f: sub('this._timer = setInterval(() => this._onTimer(), ms);', `this._timer = setInterval(() => { this._onTimer(); if (${IS_GEEK9}) this._ui.strip.hidden = true; }, ms);`) },
  { id: 'AC6-r9-E31-pagehide-neighbour-listener-hide', ac: 'AC6', note: 'a blur listener on the window, next to the allowed ones, hides the strip in Geek Mode', f: sub("window.addEventListener('pagehide', this._onPageHide);", `window.addEventListener('pagehide', this._onPageHide);\n      window.addEventListener('blur', () => { if (${IS_GEEK9}) this._ui.strip.hidden = true; });`) },
  { id: 'AC6-r9-E32-on-property-handler-hide', ac: 'AC6', note: 'an onpointerover property handler on the shell hides the strip in Geek Mode', f: gl9("    ui.shell.onpointerover = () => { if (this._ctl.mode === 'geek') ui.strip.hidden = true; };") },
  { id: 'AC12-r9-B11-cached-parts-free', ac: 'AC12', note: 'B11 (reviewer, round 9): a read reused from the cache is charged nothing, so a later snapshot reads past the snapshot budget', f: sub('  if (hit && hit.cat === cat && hit.ref === ref) return hit;', '  if (hit && hit.cat === cat && hit.ref === ref) return { ...hit, spent: 0 };') },
  { id: 'AC12-r9-B11b-cached-parts-half-price', ac: 'AC12', note: 'a cached read is charged half what it cost', f: sub('  if (hit && hit.cat === cat && hit.ref === ref) return hit;', '  if (hit && hit.cat === cat && hit.ref === ref) return { ...hit, spent: Math.floor(hit.spent / 2) };') },
  { id: 'AC12-r9-B11c-parts-ignore-catalogue', ac: 'AC12', note: 'a cached read is reused under another catalogue (stale secret key fragments, stale declared attributes)', f: sub('  if (hit && hit.cat === cat && hit.ref === ref) return hit;', '  if (hit && hit.ref === ref) return hit;') },
  { id: 'AC12-r9-B11d-parts-keyed-by-entity-id', ac: 'AC12', note: 'the reads are cached by entity id, not by state object (stale after an update)', f: chain(sub('const PARTS = new WeakMap();', 'const PARTS = new Map();'), sub('  const hit = PARTS.get(state);', '  const hit = PARTS.get(state.entity_id);'), sub('  PARTS.set(state, parts);', '  PARTS.set(state.entity_id, parts);')) },
  { id: 'AC12-r9-B11e-parts-ignore-source', ac: 'AC12', note: 'a cached read is reused for another source (the check on the source is dropped; a defensive duplicate of the catalogue check unless a state is read for two sources)', f: sub('  if (hit && hit.cat === cat && hit.ref === ref) return hit;', '  if (hit && hit.cat === cat) return hit;') },
  { id: 'AC12-r9-R01-row-reuse-ignores-clock', ac: 'AC12', note: 'a cached row is reused whatever the clock says (a stale age)', f: sub('  if (Math.abs(nowMs - hit.now) >= ROW_REUSE_MS) return false;\n', '') },
  { id: 'AC12-r9-R02-row-reuse-window-huge', ac: 'AC12', note: 'a cached row is reused for any distance in time', f: sub('const ROW_REUSE_MS = 1000;', 'const ROW_REUSE_MS = 1e12;') },
  { id: 'AC12-r9-R03-row-reuse-ignores-status-edge', ac: 'AC12', note: 'a cached row is reused across the moment its status changes', f: sub('  return cls.status === was.status && cls.flags.length === was.flags.length && cls.flags.every((f, i) => f === was.flags[i]);', '  return true;') },
  { id: 'AC12-r9-R04-row-order-stale', ac: 'AC12', note: 'a cached row keeps the place it had when an entity before it appeared', f: sub('    return hit.row.order === order ? hit.row : { ...hit.row, order };', '    return hit.row;') },
  { id: 'AC12-r9-R05-cached-row-free', ac: 'AC12', note: 'a cached row is returned with a cost of nothing', f: sub('    return hit.row.order === order ? hit.row : { ...hit.row, order };', '    return { ...hit.row, order, spent: 0 };') },
  { id: 'AC12-r9-R06-row-ignores-catalogue', ac: 'AC12', note: 'a cached row is reused under another catalogue', f: sub('  if (hit && hit.cat === cat && hit.ref === ref && hit.key === ledgerKey.key && (!present || stillRight(source, state, nowMs, hit))) {', '  if (hit && hit.ref === ref && hit.key === ledgerKey.key && (!present || stillRight(source, state, nowMs, hit))) {') },
  { id: 'AC12-r9-R07-row-ignores-ledger-key', ac: 'AC12', note: 'a cached row is reused for another ledger key', f: sub('hit.ref === ref && hit.key === ledgerKey.key && (!present', 'hit.ref === ref && (!present') },
  { id: 'AC12-r9-R09-row-cached-for-unread-too', ac: 'AC12', note: 'an entity past the budget gets its row through the cache', f: sub('  if (unread) return buildRow(source, state, nowMs, cat, order, ledgerKey, true);\n', '') },
  { id: 'AC12-r9-X01-extra-patterns-stale', ac: 'AC12', note: 'the compiled extra key patterns are those of the last catalogue compiled', f: chain(sub('  if (EXTRA_CACHE.has(list)) return EXTRA_CACHE.get(list);', '  if (EXTRA_CACHE.last) return EXTRA_CACHE.last;'), sub('  EXTRA_CACHE.set(list, out);\n  return out;', '  EXTRA_CACHE.set(list, out);\n  EXTRA_CACHE.last = out;\n  return out;')) },
  { id: 'AC12-r9-X02-prepared-catalogue-stale', ac: 'AC12', note: 'the prepared catalogue is the last one prepared, whichever catalogue is asked for', f: chain(sub('  if (key && PREP.has(key)) return PREP.get(key);', '  if (PREP.last) return PREP.last;'), sub('  if (key) PREP.set(key, prepared);', '  if (key) PREP.set(key, prepared);\n  PREP.last = prepared;')) },
  { id: 'AC12-r9-X03-key-decisions-shared-across-reads', ac: 'AC12', note: 'the key decisions of one read are kept for the next read (another entity, another catalogue)', f: chain(sub('const newCtx = (opts) => ({', 'const SHARED_KEYS = new Map();\nconst newCtx = (opts) => ({'), sub('  keys: new Map(),\n  keyCount: 0,', '  keys: SHARED_KEYS,\n  keyCount: 0,')) },
  { id: 'AC12-r9-G01-signature-without-age', ac: 'AC12', note: 'the signature of a row leaves out its age: the Geek surface shows a stale age', f: sub('showUnit, ageText, cls.ageMonitored', 'showUnit, cls.ageMonitored') },
  { id: 'AC12-r9-G02-signature-without-state', ac: 'AC12', note: 'the signature of a row leaves out its state text', f: sub("cls.flags.join(','), stateText, showUnit", "cls.flags.join(','), showUnit") },
  { id: 'AC12-r9-G03-signature-without-read-id', ac: 'AC12', note: 'the signature of a row leaves out which read it was made from (a change of attributes is not repainted)', f: sub("parts ? parts.id : unreadHere ? 'unread' : 0, ledgerKey.display]", "parts ? 0 : unreadHere ? 'unread' : 0, ledgerKey.display]") },
  { id: 'AC12-r9-G04-signature-without-status', ac: 'AC12', note: 'the signature of a row leaves out its status', f: sub("sig: [cls.status, cls.flags.join(','), stateText", "sig: [cls.flags.join(','), stateText") },
  { id: 'AC12-r9-G05-surface-row-never-rebuilt', ac: 'AC12', note: 'the Geek surface reuses the DOM of a row whatever its signature says', f: sub('      if (hit && hit.sig === sig) {', '      if (hit) {') },
  { id: 'AC12-r9-G06-surface-signature-without-open', ac: 'AC12', note: 'the Geek surface signature leaves out whether the row is open', f: sub('const sig = `${row.sig}\\u0002${open ? 1 : 0}${raw ? 1 : 0}`;', 'const sig = `${row.sig}\\u0002${raw ? 1 : 0}`;') },
  { id: 'AC9-r9-H01-problems-minus-unread-again', ac: 'AC9', note: 'H01 (reviewer, round 9): the problem sentence is counted as problems minus unread again: an unread entity that is unavailable or stale is not said', f: sub('  const n = isNum(counts.notLive) ? counts.notLive : 0;', '  const n = (isNum(counts.problems) ? counts.problems : 0) - unread;') },
  { id: 'AC9-r9-H03-notlive-counts-read-rows-only', ac: 'AC9', note: 'the not-live count leaves out the rows that were not read', f: sub("    if (r.status !== 'LIVE') counts.notLive += 1;", "    if (r.status !== 'LIVE' && !r.unread) counts.notLive += 1;") },
  { id: 'AC9-r9-H04-notlive-never-counted', ac: 'AC9', note: 'the not-live count is never made', f: sub("    if (r.status !== 'LIVE') counts.notLive += 1;\n", '') },
  { id: 'AC9-r9-H05-notlive-counts-unread-too', ac: 'AC9', note: 'the not-live count includes every unread row (the problem sentence says that live entities are stale)', f: sub("    if (r.status !== 'LIVE') counts.notLive += 1;", "    if (r.problem) counts.notLive += 1;") },
  { id: 'AC9-r9-H07-problem-sentence-only-when-all-read', ac: 'AC9', note: 'the problem sentence is dropped whenever something was not read', f: sub('  if (n > 0) notes.push(', '  if (n > 0 && unread === 0) notes.push(') },
  { id: 'AC9-r9-H08-unread-sentence-only-without-problems', ac: 'AC9', note: 'the unread sentence is dropped whenever there is a problem', f: sub('  if (unread > 0) notes.push(', '  if (unread > 0 && n === 0) notes.push(') },
  // ---- review round 10 (the reviewer's survivors A04, A05, A09, H01-H03 and K06, their variants, and the author's self-check: 49 more around the four classes). See section 22 of docs/product-ui/PRODUCTION_GEEK_MODE.md.
  // (a) THE CLOCK CLASS: a hide gated on a clock or a page state, which no test ever moved
  { id: 'AC6-r10-A04-card-clock-60s-in-geek', ac: 'AC6', note: 'A04 (reviewer, round 10): the strip is emptied once the card clock is a minute past the moment the Geek surface was built', f: chain(sub(BUILT10, `${BUILT10}\n        this._geek.bornAt = this._now();`), sub(RENDER10, `${RENDER10}\n    if (this._geek && this._geek.bornAt !== undefined && now - this._geek.bornAt >= 60000) ui.strip.replaceChildren();`)) },
  { id: 'AC6-r10-A05-performance-now-20s-in-geek', ac: 'AC6', note: 'A05 (reviewer, round 10): the same on performance.now, twenty seconds', f: chain(sub(BUILT10, `${BUILT10}\n        this._geek.bornAt = performance.now();`), sub(RENDER10, `${RENDER10}\n    if (this._geek && this._geek.bornAt !== undefined && performance.now() - this._geek.bornAt >= 20000) ui.strip.replaceChildren();`)) },
  { id: 'AC6-r10-O01-date-now-30s-in-geek', ac: 'AC6', note: 'the same on Date.now, thirty seconds', f: chain(sub(BUILT10, `${BUILT10}\n        this._geek.bornAt = Date.now();`), sub(RENDER10, `${RENDER10}\n    if (this._geek && this._geek.bornAt !== undefined && Date.now() - this._geek.bornAt >= 30000) ui.strip.replaceChildren();`)) },
  { id: 'AC6-r10-O02-visibilitystate-hidden-in-geek', ac: 'AC6', note: 'a hidden tab (visibilityState) empties the strip in Geek Mode', f: sub(RENDER10, `${RENDER10}\n    if (this.ownerDocument.visibilityState === 'hidden' && this._ctl.mode === 'geek') ui.strip.replaceChildren();`) },
  { id: 'AC6-r10-O03-document-hidden-any-mode', ac: 'AC6', note: 'a hidden document empties the strip in either mode', f: sub(RENDER10, `${RENDER10}\n    if (this.ownerDocument.hidden === true) ui.strip.replaceChildren();`) },
  { id: 'AC6-r10-O04-card-clock-two-hours-since-connect-any-mode', ac: 'AC6', note: 'two hours of the card clock after the connect empty the strip, in either mode', f: chain(sub('    this._connected = true;\n    this._entryPath = this._pathNow();', '    this._connected = true;\n    this._bornP = this._now();\n    this._entryPath = this._pathNow();'), sub(RENDER10, `${RENDER10}\n    if (this._bornP !== undefined && now - this._bornP >= 7200000) ui.strip.replaceChildren();`)) },
  { id: 'AC6-r10-O05-gap-since-previous-rebuild-ten-minutes', ac: 'AC6', note: 'a gap of ten minutes since the previous rebuild empties the strip', f: sub(RENDER10, `${RENDER10}\n    if (this._prevAt !== undefined && now - this._prevAt > 600000) ui.strip.replaceChildren();\n    this._prevAt = now;`) },
  { id: 'AC6-r10-O06-hasfocus-lost-in-geek', ac: 'AC6', note: 'a window that lost focus empties the strip in Geek Mode', f: sub(RENDER10, `${RENDER10}\n    if (typeof this.ownerDocument.hasFocus === 'function' && !this.ownerDocument.hasFocus() && this._ctl.mode === 'geek') ui.strip.replaceChildren();`) },
  { id: 'AC6-r10-O07-admit-uptime-three-hours', ac: 'AC6', note: 'the burst control empties the strip once performance.now is three hours', f: sub('    if (!this._connected) return true;\n    const t = typeof performance', "    if (!this._connected) return true;\n    if (this._ui && typeof performance !== 'undefined' && performance.now() > 10800000) this._ui.strip.replaceChildren();\n    const t = typeof performance") },
  { id: 'AC6-r10-O08-navigator-offline', ac: 'AC6', note: 'a browser that is offline empties the strip', f: sub(RENDER10, `${RENDER10}\n    if (typeof navigator !== 'undefined' && navigator.onLine === false) ui.strip.replaceChildren();`) },
  { id: 'AC6-r10-O09-narrow-media-query', ac: 'AC6', note: 'a narrow media query empties the strip', f: sub(RENDER10, `${RENDER10}\n    if (typeof window.matchMedia === 'function' && window.matchMedia('(max-width: 400px)').matches) ui.strip.replaceChildren();`) },
  { id: 'AC6-r10-O10-alerts-dropped-when-more-than-three-sources-are-stale', ac: 'AC6', note: 'time makes sources stale, and more than three stale sources drop every alert of the catalogue', f: sub('    this._alerts = [...deriveAlerts(this._snap, cat), ...this._shellAlerts];', '    this._alerts = this._snap.counts.STALE > 3 ? [...this._shellAlerts] : [...deriveAlerts(this._snap, cat), ...this._shellAlerts];') },
  { id: 'AC6-r10-O11-third-tick-hides-in-production', ac: 'AC6', note: 'the fourth tick empties the strip in Production', f: sub('  _tick() {\n    this._refresh(true);\n  }', "  _tick() {\n    this._refresh(true);\n    this._ticks = (this._ticks || 0) + 1;\n    if (this._ticks > 3 && this._ctl.mode === 'production') this._ui.strip.replaceChildren();\n  }") },
  { id: 'AC6-r10-O12-non-critical-alerts-dropped-after-26-hours', ac: 'AC6', note: 'after 26 hours of the card clock only the critical alerts are drawn', f: sub(RENDER10, "    if (this._t0 === undefined) this._t0 = now;\n    renderAlertStrip(this.ownerDocument, ui.strip, now - this._t0 > 93000000 ? this._alerts.filter((a) => a.severity === 'critical') : this._alerts);") },
  { id: 'AC6-r10-O13-geek-reentry-after-fifteen-minutes-hides', ac: 'AC6', note: 'entering Geek Mode again fifteen minutes after the last time empties the strip', f: sub('      if (!this._geek) {\n        this._geek = new GeekSurface({', "      if (this._lastGeekAt !== undefined && this._now() - this._lastGeekAt >= 900000) ui.strip.replaceChildren();\n      this._lastGeekAt = this._now();\n      if (!this._geek) {\n        this._geek = new GeekSurface({") },
  { id: 'AC6-r10-O14-timer-firing-an-hour-after-the-first-hides', ac: 'AC6', note: 'the timer hides the strip an hour (performance.now) after its first firing', f: sub('  _onTimer() {\n    if (this._timerMs !== TICK_MS) this._startTimer(TICK_MS);', "  _onTimer() {\n    this._firstTimer = this._firstTimer === undefined ? performance.now() : this._firstTimer;\n    if (performance.now() - this._firstTimer > 3600000) this._ui.strip.hidden = true;\n    if (this._timerMs !== TICK_MS) this._startTimer(TICK_MS);") },
  // (b) THE BODIES of the continuations
  { id: 'AC6-r10-A09-attach-in-geek-empties', ac: 'AC6', note: 'A09 (reviewer, round 10): attach() empties the strip when it runs in Geek Mode (a child built after the switch)', f: sub('      wrap.appendChild(el);\n      this._kids.push(el);', "      wrap.appendChild(el);\n      this._kids.push(el);\n      if (this._ctl.mode === 'geek') this._ui.strip.replaceChildren();") },
  { id: 'AC6-r10-F01-fail-in-geek-empties', ac: 'AC6', note: 'the fail variant of A09: fail() empties the strip in Geek Mode (a child that could not be made after the switch)', f: sub("      if (gen === this._gen) wrap.appendChild(this._notice('data-child-error', `Card could not be shown: ${message}`));", "      if (gen === this._gen) wrap.appendChild(this._notice('data-child-error', `Card could not be shown: ${message}`));\n      if (this._ctl.mode === 'geek') this._ui.strip.replaceChildren();") },
  { id: 'AC6-r10-S01-say-in-geek-empties', ac: 'AC6', note: 'the say variant of A09: say() empties the strip in Geek Mode (a clipboard answer after the switch)', f: sub('    const say = (m) => {\n      if (this._geek) this._geek.say(m);\n    };', "    const say = (m) => {\n      if (this._geek) this._geek.say(m);\n      if (this._ctl.mode === 'geek') this._ui.strip.replaceChildren();\n    };") },
  { id: 'AC6-r10-O20-attach-third-child-empties-strip', ac: 'AC6', note: 'the third child to arrive empties the strip, in either mode', f: sub('      this._kids.push(el);\n      if (this._hass', '      this._kids.push(el);\n      if (this._kids.length > 2) this._ui.strip.replaceChildren();\n      if (this._hass') },
  { id: 'AC6-r10-O21-fail-in-production-empties-strip', ac: 'AC6', note: 'fail() empties the strip when it runs in Production', f: sub("      if (gen === this._gen) wrap.appendChild(this._notice('data-child-error', `Card could not be shown: ${message}`));", "      if (gen === this._gen) wrap.appendChild(this._notice('data-child-error', `Card could not be shown: ${message}`));\n      if (this._ctl.mode === 'production') this._ui.strip.replaceChildren();") },
  { id: 'AC6-r10-O22-clipboard-refusal-empties-strip', ac: 'AC6', note: 'the refusal of the clipboard empties the strip', f: sub("() => say('The browser blocked the copy. Use the JSON or CSV button instead.'));", "() => { say('The browser blocked the copy. Use the JSON or CSV button instead.'); this._ui.strip.replaceChildren(); });") },
  { id: 'AC6-r10-O23-no-clipboard-empties-strip', ac: 'AC6', note: 'a browser with no clipboard empties the strip when it says so', f: sub("      say('Copy is not available in this browser context. Use the JSON or CSV button instead.');\n      return;", "      say('Copy is not available in this browser context. Use the JSON or CSV button instead.');\n      this._ui.strip.replaceChildren();\n      return;") },
  { id: 'AC6-r10-O24-download-empties-strip', ac: 'AC6', note: 'a download empties the strip after it says so', f: sub("    if (this._geek) this._geek.say(`Downloaded ${format.toUpperCase()} (non-secret values only).`);", "    if (this._geek) this._geek.say(`Downloaded ${format.toUpperCase()} (non-secret values only).`);\n    this._ui.strip.replaceChildren();") },
  { id: 'AC6-r10-O25-geek-say-reaches-strip-through-container', ac: 'AC6', note: 'the Geek surface reaches the strip through its container when it says something', f: sub('    if (this.ui.status_line) this.ui.status_line.textContent = text;', "    if (this.ui.status_line) this.ui.status_line.textContent = text;\n    this.o.container.parentNode.querySelector('[data-ecco-alert-strip]').replaceChildren();") },
  { id: 'AC6-r10-O26-attach-blanks-first-alert-line', ac: 'AC6', note: 'attach() blanks the text of the first alert line', f: sub('      this._kids.push(el);\n      if (this._hass', "      this._kids.push(el);\n      if (this._ui.strip.firstChild) this._ui.strip.firstChild.textContent = '';\n      if (this._hass") },
  { id: 'AC7-r10-O27-attach-forgets-to-hand-over-hass', ac: 'AC7', note: 'a child that arrives late is never given the hass it missed', f: sub('      if (this._hass !== null && this._hass !== undefined) el.hass = this._hass;\n', '') },
  // (c) THE NOT-LIVE COUNT and the other fields of counts
  { id: 'AC9-r10-H01-notlive-skips-not-measured', ac: 'AC9', note: 'H01 (reviewer, round 10): the not-live count skips the rows that are not measured (a declared source with no entity)', f: sub(NOTLIVE10, "    if (r.status !== 'LIVE' && r.status !== 'NOT_MEASURED') counts.notLive += 1;") },
  { id: 'AC9-r10-H02-notlive-skips-discovered', ac: 'AC9', note: 'H02 (reviewer, round 10): the not-live count skips the discovered rows', f: sub(NOTLIVE10, "    if (r.status !== 'LIVE' && !r.discovered) counts.notLive += 1;") },
  { id: 'AC9-r10-H03-notlive-skips-unknown', ac: 'AC9', note: 'H03 (reviewer, round 10): the not-live count skips the unknown rows', f: sub(NOTLIVE10, "    if (r.status !== 'LIVE' && r.status !== 'UNKNOWN') counts.notLive += 1;") },
  { id: 'AC9-r10-O30-notlive-skips-stale', ac: 'AC9', note: 'the not-live count skips the stale rows', f: sub(NOTLIVE10, "    if (r.status !== 'LIVE' && r.status !== 'STALE') counts.notLive += 1;") },
  { id: 'AC9-r10-O31-notlive-skips-simulated', ac: 'AC9', note: 'the not-live count skips the simulated rows', f: sub(NOTLIVE10, "    if (r.status !== 'LIVE' && r.status !== 'SIMULATED') counts.notLive += 1;") },
  { id: 'AC9-r10-O32-notlive-skips-unverified', ac: 'AC9', note: 'the not-live count skips the unverified rows', f: sub(NOTLIVE10, "    if (r.status !== 'LIVE' && r.status !== 'UNVERIFIED') counts.notLive += 1;") },
  { id: 'AC9-r10-O33-notlive-skips-unavailable-discovered', ac: 'AC9', note: 'the not-live count skips the unavailable discovered rows only', f: sub(NOTLIVE10, "    if (r.status !== 'LIVE' && !(r.discovered && r.status === 'UNAVAILABLE')) counts.notLive += 1;") },
  { id: 'AC9-r10-O34-discovered-counts-live-ones-only', ac: 'AC9', note: 'the discovered count only counts the discovered rows that are live', f: sub('    if (r.discovered) counts.discovered += 1;', "    if (r.discovered && r.status === 'LIVE') counts.discovered += 1;") },
  { id: 'AC9-r10-O35-total-excludes-discovered', ac: 'AC9', note: 'the total leaves the discovered rows out', f: sub('const counts = { total: rows.length, withheld: 0,', 'const counts = { total: rows.filter((r) => !r.discovered).length, withheld: 0,') },
  { id: 'AC9-r10-O36-problems-skip-discovered', ac: 'AC9', note: 'the problems count leaves the discovered rows out', f: sub('    if (r.problem) counts.problems += 1;', '    if (r.problem && !r.discovered) counts.problems += 1;') },
  { id: 'AC9-r10-O37-unread-skips-discovered', ac: 'AC9', note: 'the unread count leaves the discovered rows out', f: sub('    if (r.unread) counts.unread += 1;', '    if (r.unread && !r.discovered) counts.unread += 1;') },
  { id: 'AC9-r10-O38-status-counts-skip-discovered', ac: 'AC9', note: 'the count of each status leaves the discovered rows out', f: sub('    counts[r.status] += 1;', '    if (!r.discovered) counts[r.status] += 1;') },
  { id: 'AC9-r10-O39-withheld-counts-rows-not-values', ac: 'AC9', note: 'the withheld count counts rows, not values', f: sub('    counts.withheld += r.withheld;', '    counts.withheld += r.withheld ? 1 : 0;') },
  { id: 'AC9-r10-O40-sentence-plural-swapped', ac: 'AC9', note: 'the Production sentence says "is" for many and "are" for one', f: sub("${n} data point${n === 1 ? ' is' : 's are'} stale", "${n} data point${n === 1 ? 's are' : ' is'} stale") },
  { id: 'AC9-r10-O41-sentence-back-to-round-9-wording', ac: 'AC9', note: 'the Production sentence does not name the unknown and not-measured rows it counts (the wording of round 9)', f: sub('stale, unavailable, unknown, not measured, simulated or unverified. Geek Mode lists them.', 'stale, unavailable, simulated or unverified. Geek Mode lists them.') },
  { id: 'AC9-r10-O42-notlive-counts-every-row', ac: 'AC9', note: 'the not-live count counts every row, live ones too', f: sub(NOTLIVE10, "    if (r.status !== 'NOTHING') counts.notLive += 1;") },
  { id: 'AC9-r10-O43-sentence-reads-unread-count-for-the-number', ac: 'AC9', note: 'the number in the problem sentence is the unread count', f: sub('  const n = isNum(counts.notLive) ? counts.notLive : 0;', '  const n = isNum(counts.unread) ? counts.unread : 0;') },
  // (d) THE KEY COUNT, the watched set and the caches
  { id: 'AC12-r10-K06-samewatched-ignores-key-count', ac: 'AC12', note: 'K06 (reviewer, round 10): the key-count comparison is dropped from the watched-set check, so a new entity within a second of the last rebuild waits for the tick', f: sub(SAMEW10, '    if (watch === null) return false;') },
  { id: 'AC12-r10-O50-key-count-checked-only-without-alerts', ac: 'AC12', note: 'the key count is compared only when no alert is on the strip', f: sub(SAMEW10, '    if (watch === null || (this._alerts.length === 0 && Object.keys(states).length !== this._keyCount)) return false;') },
  { id: 'AC12-r10-O51-key-count-less-than-misses-additions', ac: 'AC12', note: 'the key count is compared with "less than", so an entity that is added is not noticed', f: sub(SAMEW10, '    if (watch === null || Object.keys(states).length < this._keyCount) return false;') },
  { id: 'AC12-r10-O52-key-count-greater-than-misses-removals', ac: 'AC12', note: 'the key count is compared with "greater than": the count of the last rebuild is never lowered, so a removal followed by an addition is missed (first judged equivalent; the seeded history of round 10 killed it)', f: sub(SAMEW10, '    if (watch === null || Object.keys(states).length > this._keyCount) return false;') },
  { id: 'AC12-r10-O58-last-states-not-stored-on-skip', ac: 'AC12', note: 'a skipped update does not remember its states object, so the same object again is compared again (a cost: killed by counting the comparisons)', f: sub('      if (now - this._lastNow < 1000 && this._sameWatched(states)) {\n        this._lastStates = states;\n        return;', '      if (now - this._lastNow < 1000 && this._sameWatched(states)) {\n        return;') },
  { id: 'AC12-r10-O53-watched-compare-skips-last-entry', ac: 'AC12', note: 'the watched-set comparison leaves the last watched entity out', f: sub('    for (const [id, st] of watch) if (states[id] !== st) return false;', '    for (const [id, st] of watch.slice(0, -1)) if (states[id] !== st) return false;') },
  { id: 'AC12-r10-O54-key-count-never-stored', ac: 'AC12', note: 'the key count is never stored, so it never matches', f: sub('    this._keyCount = Object.keys(states).length;\n', '') },
  { id: 'AC12-r10-O55-last-now-not-stored-on-rebuild', ac: 'AC12', note: 'the clock of the last rebuild is never stored', f: sub('    this._lastStates = states;\n    this._lastNow = now;\n', '    this._lastStates = states;\n') },
  { id: 'AC12-r10-O56-skip-window-100-seconds', ac: 'AC12', note: 'an update the view does not read is skipped for a hundred seconds, not one', f: sub('      if (now - this._lastNow < 1000 && this._sameWatched(states)) {', '      if (now - this._lastNow < 100000 && this._sameWatched(states)) {') },
  { id: 'AC12-r10-O57-watch-list-never-stored', ac: 'AC12', note: 'the watched list is never stored', f: sub('    this._watch = this._snap.watch.map((id) => [id, states[id]]);\n', '') },
  { id: 'AC12-r10-O59-parts-cache-ignores-catalogue', ac: 'AC12', note: 'the read of a state object is reused under another catalogue', f: sub('  if (hit && hit.cat === cat && hit.ref === ref) return hit;\n  STATS.partsBuilt += 1;', '  if (hit && hit.ref === ref) return hit;\n  STATS.partsBuilt += 1;') },
  { id: 'AC12-r10-O60-row-cache-ignores-source-ref', ac: 'AC12', note: 'a cached row is reused for another source of the same entity', f: sub('  if (hit && hit.cat === cat && hit.ref === ref && hit.key === ledgerKey.key', '  if (hit && hit.cat === cat && hit.key === ledgerKey.key') },
  { id: 'AC12-r10-O61-discovered-ids-not-watched', ac: 'AC12', note: 'the discovered entities are not in the watched set', f: sub('    found.forEach((id, i) => {\n      watch.add(id);\n', '    found.forEach((id, i) => {\n') },
  { id: 'AC12-r10-O62-key-count-compared-to-watch-length', ac: 'AC12', note: 'the key count is compared with the length of the watched list', f: sub(SAMEW10, '    if (watch === null || Object.keys(states).length !== watch.length) return false;') },
];

const MIN = { AC5: 6, AC6: 6, AC10: 6, AC13: 6 };

// ---- review round 9: THE RUNNER RULE (reviewer NIT). Some tests assert how LONG something took (they carry [wall-clock] in their title: static.test.mjs checks that every test that reads the clock does). Under the parallel load of this runner
// such a test can fail for no fault of the card, and a mutant whose ONLY failing tests are of that kind may be "killed" by the load: the reviewer saw E08 killed at four processes at a time and alive at one. So: a mutant whose
// every failing test is a wall-clock test is run AGAIN, alone, one test file at a time, after the parallel part is over, and counts as killed only if it fails again. (A mutant killed by any test that is not a wall-clock test needs no second run:
// those tests do not depend on the load.)
const WALL_CLOCK = '[wall-clock]';
/** The titles of the tests that failed in a run of `node --test` (spec reporter: a line at the start of a line, the failure mark, the title and the time it took). */
const failedTitles = (out) => [...new Set([...String(out).matchAll(/^\u2716 (.+?) \(\d+(?:\.\d+)?ms\)\s*$/gm)].map((m) => m[1].trim()))];
/** True when the run failed and every test that failed is a wall-clock test (a run that failed with no test named, a crash or a file that did not load, is not). */
const killedOnlyByTiming = (run) => {
  if (!run || run.code === 0) return false;
  const titles = failedTitles(run.out);
  return titles.length > 0 && titles.every((t) => t.includes(WALL_CLOCK));
};
/** Killed: the run failed, and if it failed only on timing, it failed again when run alone. */
const isKilled = (m) => m.run !== null && m.run.code !== 0 && (!m.timingOnly || (m.serial !== undefined && m.serial.code !== 0));

// --test-force-exit: a mutant that leaks a timer (a second interval that nothing clears) must not keep the test process, and with it this whole run, alive for ever once its tests are over.
// --test-concurrency: review round 9 (two earlier attempts of the round ran the PC out of virtual memory): a bare `node --test` runs as many test files at once as the machine has cores, in every one of the six runs of the pool, so
// each run is held to two files at a time (one, for the run alone that the runner rule asks for). The heap cap and the per-process memory guard are inherited from the environment of the outer run.
const CHILD_CONCURRENCY = 2;
// A time limit for one nested run (review round 9). In one of three full runs of the proof a nested test-file process of a mutant went idle (no CPU, no port) and stayed so for thirty minutes, with every other run long over;
// the same mutant and file ran clean three times alone, so it was not the card. A run that does not finish is killed (with its whole tree) and run once more alone; a mutant whose run hangs twice is reported by name and counts
// as killed (a suite that never ends fails any pipeline). The normal nested run takes under a minute (the perf and differential suites a few more).
const RUN_LIMIT_MS = 300000;
const BASELINE_LIMIT_MS = 900000;
const killTree = (child) => {
  if (process.platform === 'win32') spawnSync('taskkill', ['/pid', String(child.pid), '/T', '/F'], { stdio: 'ignore' });
  else child.kill('SIGKILL');
};
/** The result of a run that may have hung: the first run if it finished; else the second if that finished; else a failed run that says it hung. */
const resolveHang = (first, again) => {
  if (!first.timedOut) return first;
  if (again && !again.timedOut) return { ...again, retried: true };
  return { code: 1, out: `${first.out}\n${again ? again.out : ''}`, hung: true };
};
function runSuites(file, extra = [], { serial = false, limitMs = RUN_LIMIT_MS } = {}) {
  return new Promise((resolve) => {
    // NODE_TEST_CONTEXT is set by the outer test runner; inherited, it would turn the nested `node --test` into a silent no-op.
    const env = { ...process.env, ECCO_MODE_SHELL_PATH: file, ECCO_SKIP_MUTATIONS: '1' };
    delete env.NODE_TEST_CONTEXT;
    const child = spawn(process.execPath, ['--test', '--test-force-exit', `--test-concurrency=${serial ? 1 : CHILD_CONCURRENCY}`, ...SUITES, ...extra], { env, stdio: ['ignore', 'pipe', 'pipe'] });
    let out = '';
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      killTree(child);
    }, limitMs);
    child.stdout.on('data', (d) => { out += d; });
    child.stderr.on('data', (d) => { out += d; });
    child.on('close', (code) => {
      clearTimeout(timer);
      resolve({ code: timedOut ? 124 : code, out, timedOut });
    });
  });
}
/** One nested run; if it hangs, once more alone (see resolveHang). */
async function runChecked(file, extra, opts = {}) {
  const first = await runSuites(file, extra, opts);
  return first.timedOut ? resolveHang(first, await runSuites(file, extra, { ...opts, serial: true })) : first;
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
  const baseline = await runChecked(baseFile, [PERF_SUITE, DIFF_SUITE], { limitMs: BASELINE_LIMIT_MS });
  const results = await pool(prepared, 6, async (m) => (m.file ? { ...m, run: await runChecked(m.file, extraSuites(m)) } : { ...m, run: null }));
  // review round 9, the runner rule: a mutant that failed only on wall-clock tests is run again, alone, before it counts as killed
  for (const m of results) {
    m.timingOnly = killedOnlyByTiming(m.run);
    if (m.timingOnly) m.serial = await runChecked(m.file, extraSuites(m), { serial: true });
  }
  // The extra layer (review round 5): where Chrome or Edge is installed, the mutants marked browser: true are also given to the headless browser check, one after the other (each starts
  // its own browser). The node suites above must kill every mutant by themselves; this layer only adds a second opinion, and is skipped, loudly, where there is no browser.
  const browserPath = findBrowser();
  const browserRuns = [];
  if (browserPath) {
    for (const m of results.filter((x) => x.browser && x.file)) {
      const checkScript = path.join(cardDir, 'preview', 'check-strip.mjs');
      const env = { ...process.env, ECCO_CHROME: browserPath };
      delete env.NODE_TEST_CONTEXT;
      browserRuns.push({ id: m.id, ...(await new Promise((resolve) => {
        const child = spawn(process.execPath, [checkScript, '--require', '--card', m.file], { env, stdio: ['ignore', 'pipe', 'pipe'] });
        let out = '';
        child.stdout.on('data', (d) => { out += d; });
        child.stderr.on('data', (d) => { out += d; });
        child.on('close', (code) => resolve({ code, out: out.slice(-600) }));
      })) });
    }
  }
  rmSync(dir, { recursive: true, force: true });

  test('mutation table [r8]: every mutant has an id of its own (the file of a mutant is named by its id, so two with one id would run only the last of them)', () => {
    const seen = new Set();
    for (const m of MUTANTS) {
      assert.ok(!seen.has(m.id), `the id ${m.id} is used twice`);
      seen.add(m.id);
    }
  });

  test('mutation baseline: the unmutated copy passes the suites it is run against (the harness works)', () => {
    assert.equal(baseline.code, 0, baseline.out.slice(-2000));
  });

  for (const m of results) {
    test(`mutant ${m.id} (${m.ac}): ${m.note}: is killed`, () => {
      assert.equal(m.error, null, m.error);
      assert.notEqual(m.run.code, 0, `SURVIVED: no test failed with this break`);
      assert.equal(isKilled(m), true, `SURVIVED when run alone: only wall-clock tests failed (${failedTitles(m.run.out).join(' | ').slice(0, 300)}), and they passed on a second run with nothing else running`);
    });
  }

  test('mutation runner [r9]: the rule for a failure of wall-clock tests alone is applied as stated (the logic, on made-up outputs of the test runner)', () => {
    const fail = (...titles) => ({ code: 1, out: titles.map((t) => `\u2716 ${t} (12.5ms)`).join('\n') });
    assert.deepEqual(failedTitles(`\u2714 a (1ms)\n\u2716 one (2.25ms)\n  \u2716 indented is not a title (1ms)\n\u2716 two (3ms)\n\u2716 one (2.25ms)`), ['one', 'two'], 'titles of failures at the start of a line, once each');
    assert.equal(killedOnlyByTiming(fail(`${WALL_CLOCK} AC12 the first snapshot is fast`)), true, 'one wall-clock test');
    assert.equal(killedOnlyByTiming(fail(`${WALL_CLOCK} a`, `${WALL_CLOCK} b`)), true, 'two');
    assert.equal(killedOnlyByTiming(fail(`${WALL_CLOCK} a`, 'AC6 the strip is the same')), false, 'one wall-clock test and one behavioural test: the behavioural one kills it');
    assert.equal(killedOnlyByTiming(fail('AC6 the strip is the same')), false);
    assert.equal(killedOnlyByTiming({ code: 1, out: 'SyntaxError: nothing named' }), false, 'a crash names no test: it is not a timing failure');
    assert.equal(killedOnlyByTiming({ code: 0, out: `\u2716 ${WALL_CLOCK} a (1ms)` }), false, 'a passing run is not killed by anything');
    assert.equal(killedOnlyByTiming(null), false);
    const timing = { ...{ run: fail(`${WALL_CLOCK} a`) }, timingOnly: true };
    assert.equal(isKilled(timing), false, 'killed only by timing and not yet run alone: not killed');
    assert.equal(isKilled({ ...timing, serial: { code: 0, out: '' } }), false, 'and it passed alone: it SURVIVES');
    assert.equal(isKilled({ ...timing, serial: { code: 1, out: '' } }), true, 'and it failed again alone: killed');
    assert.equal(isKilled({ run: fail('AC6 x'), timingOnly: false }), true, 'a behavioural failure is a kill at once');
    assert.equal(isKilled({ run: { code: 0, out: '' }, timingOnly: false }), false);
    assert.equal(isKilled({ run: null }), false);
  });

  test('mutation runner [r9]: a nested run that hits the time limit is run again alone; one that finishes the second time counts as that run, one that hangs twice is a failed run that says so (the logic, on made-up results)', () => {
    const done = { code: 0, out: 'ok', timedOut: false };
    const failed = { code: 1, out: '\u2716 AC6 x (3ms)', timedOut: false };
    const hang = { code: 124, out: 'partial', timedOut: true };
    assert.equal(resolveHang(done, null), done, 'a run that finished is the run');
    assert.equal(resolveHang(failed, null), failed);
    assert.deepEqual(resolveHang(hang, done), { ...done, retried: true }, 'a hang, then a pass: the pass counts, and it is said that the first run hung');
    assert.deepEqual(resolveHang(hang, failed), { ...failed, retried: true }, 'a hang, then a failure: the failure');
    const twice = resolveHang(hang, hang);
    assert.equal(twice.hung, true);
    assert.notEqual(twice.code, 0, 'a mutant whose suites never end is killed, and named');
    assert.equal(killedOnlyByTiming(twice), false, 'and a hang is never mistaken for a timing failure');
    assert.equal(isKilled({ run: twice, timingOnly: false }), true);
    assert.ok(RUN_LIMIT_MS >= 120000 && RUN_LIMIT_MS <= 600000 && BASELINE_LIMIT_MS > RUN_LIMIT_MS);
  });

  if (browserPath) {
    for (const b of browserRuns) {
      test(`mutant ${b.id}: the headless browser check (extra layer) fails it too`, () => {
        assert.equal(b.code, 1, `exit code ${b.code} (1 means a check failed): ${b.out}`);
      });
    }
    test('mutation browser layer: at least five mutants were also given to the browser check', () => {
      assert.ok(browserRuns.length >= 5, `${browserRuns.length} browser runs`);
    });
  } else {
    test('mutation browser layer: no Chrome or Edge found, so the extra layer did not run (the node suites above killed every mutant by themselves)', { skip: 'no browser installed' }, () => {});
  }

  test('mutation coverage: each case that needs a mutation proof has enough mutants, and all were killed', () => {
    const per = {};
    for (const m of results) per[m.ac] = (per[m.ac] || 0) + 1;
    for (const [ac, n] of Object.entries(MIN)) assert.ok((per[ac] || 0) >= n, `${ac} has ${per[ac] || 0} mutants, needs ${n}`);
    const survivors = results.filter((m) => m.error !== null || !isKilled(m)).map((m) => m.id);
    const rerun = results.filter((m) => m.timingOnly).map((m) => `${m.id}: ${m.serial.code !== 0 ? 'killed again alone' : 'SURVIVED alone'}`);
    if (rerun.length) console.log(`mutants killed only by wall-clock tests, run again alone: ${rerun.join('; ')}`);
    const retried = results.filter((m) => m.run && m.run.retried).map((m) => m.id);
    const hung = results.filter((m) => m.run && m.run.hung).map((m) => m.id);
    if (retried.length) console.log(`mutants whose first run hit the time limit and finished when run again alone: ${retried.join('; ')}`);
    if (hung.length) console.log(`mutants whose run hit the time limit twice (counted as killed, by name): ${hung.join('; ')}`);
    assert.deepEqual(survivors, []);
    console.log(`mutation score: ${results.length - survivors.length}/${results.length} killed; per case ${JSON.stringify(per)}`);
  });
}
