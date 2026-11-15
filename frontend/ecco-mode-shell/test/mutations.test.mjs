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
import { findBrowser } from '../preview/check-strip.mjs';

const nested = process.env.ECCO_MODE_SHELL_PATH !== undefined || process.env.ECCO_SKIP_MUTATIONS === '1';
const REAL = path.join(cardDir, 'ecco-mode-shell.js');
const SUITES = ['core.test.mjs', 'element.test.mjs', 'static.test.mjs', 'coverage.test.mjs', 'real-catalogue.test.mjs'].map((f) => path.join(cardDir, 'test', f));

/** sub(find, replace[, all]): replace the one occurrence of `find` (or every occurrence with all = true). */
const sub = (find, replace, all = false) => (s) => {
  const n = s.split(find).length - 1;
  if (n === 0 || (n > 1 && !all)) throw new Error(`mutation target found ${n} times: ${find.slice(0, 80)}`);
  return s.split(find).join(replace);
};
const chain = (...fs) => (s) => fs.reduce((acc, f) => f(acc), s);
const GEEK_LINE = "    ui.geekBody.hidden = mode !== 'geek';";
const SCAN_LINE = '  if (valueReason(t, digestOk, digestKey) !== null) return WITHHELD;';

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
  { id: 'AC10-extra-patterns-ignored', ac: 'AC10', note: 'the catalogue extra key patterns are ignored', f: sub('  return keyHasFragment(fold(String(key)), extra);', '  return false;') },
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
  { id: 'AC10-extra-patterns-not-prepared', ac: 'AC10', note: 'the catalogue extra key patterns never reach the redactor', f: sub('const opts = { extraKeyPatterns: cat.extraPatterns };', 'const opts = { extraKeyPatterns: [] };') },
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
  { id: 'AC6-not-in-inverted', ac: 'AC6', note: 'not_in fires when the value IS listed', f: sub("if (when.not_in) return when.not_in.some((x) => x === v) ? 'clear' : 'active';", "if (when.not_in) return when.not_in.some((x) => x === v) ? 'active' : 'clear';") },
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
  { id: 'AC10-webhook-services-form-dropped', ac: 'AC10', note: 'the chat services webhook path is shown', f: sub('|hooks\\.[a-z0-9.-]+\\/services\\/[A-Za-z0-9/_-]{12,}/i],', '/i],') },
  { id: 'AC10-login-key-rule-dropped', ac: 'AC10', note: 'a key such as mqtt_user or db_login is shown', f: sub('  if (tokens.length >= 2 && LOGIN_WORDS.has(tokens[tokens.length - 1])) return true;\n', '') },
  { id: 'AC10-login-key-needs-no-qualifier', ac: 'AC10', note: 'a bare user key is withheld too (the rule needs a qualifier, as the key rule does)', f: sub('  if (tokens.length >= 2 && LOGIN_WORDS.has(tokens[tokens.length - 1])) return true;', '  if (LOGIN_WORDS.has(tokens[tokens.length - 1])) return true;') },
  // ---- review round 3: state_not_in fail-safe (R3-20) and the redaction gaps
  { id: 'AC6-not-in-down-honours-list', ac: 'AC6', note: 'state_not_in reads a down entity (unknown, unavailable) against the list instead of firing (reviewer mutant R3-20)', f: sub("if (when.state_not_in) return down || !when.state_not_in.includes(input.state) ? 'active' : 'clear';", "if (when.state_not_in) return !input.present || !when.state_not_in.includes(input.state) ? 'active' : 'clear';") },
  { id: 'AC10-pass-last-word-dropped', ac: 'AC10', note: 'a key such as wifi_pass is shown', f: sub('  if (tokens.length >= 2 && PASS_WORDS.has(tokens[tokens.length - 1])) return true;\n', '') },
  { id: 'AC10-bare-pass-withheld', ac: 'AC10', note: 'a bare pass key is withheld too (it is also a test result: the rule needs a qualifier)', f: sub('  if (tokens.length >= 2 && PASS_WORDS.has(tokens[tokens.length - 1])) return true;\n', '  if (PASS_WORDS.has(tokens[tokens.length - 1])) return true;\n') },
  { id: 'AC10-pw-token-dropped', ac: 'AC10', note: 'a key named pw is shown', f: sub("'refreshtoken', 'pw', 'wifipass', 'wifipw']);", "'refreshtoken', 'wifipass', 'wifipw']);") },
  { id: 'AC10-wifipass-token-dropped', ac: 'AC10', note: 'the compact keys wifipass and wifipw are shown', f: sub("'refreshtoken', 'pw', 'wifipass', 'wifipw']);", "'refreshtoken', 'pw']);") },
  { id: 'AC10-mac-dotted-dropped', ac: 'AC10', note: 'a MAC address in the dotted form is shown', f: sub("['MAC address (dotted)', '.',", "['MAC address (dotted)', 'zzzz',") },
  { id: 'AC10-mac-dotted-versions', ac: 'AC10', note: 'the dotted-MAC rule takes any dotted hex or digit text, so a version number is withheld', f: sub('/\\b(?=[0-9a-f.]*[a-f])[0-9a-f]{4}\\.', '/\\b[0-9a-f]{4}\\.') },
  { id: 'AC10-mac12-dropped', ac: 'AC10', note: 'a MAC address with no separators is shown', f: sub("if (!digestKey && RE_MAC12.test(s)) return 'MAC address (no separators)';", '') },
  { id: 'AC10-mac12-ignores-revision-key', ac: 'AC10', note: 'the no-separator rule also withholds a short git revision under a revision key', f: sub('if (!digestKey && RE_MAC12.test(s))', 'if (RE_MAC12.test(s))') },
  { id: 'AC10-mac12-takes-digits', ac: 'AC10', note: 'the no-separator rule takes any twelve digits, so a plain number is withheld', f: sub('const RE_MAC12 = /^\\s*(?=[0-9a-f]*[a-f])[0-9a-f]{12}\\s*$/i;', 'const RE_MAC12 = /^\\s*[0-9a-f]{12}\\s*$/i;') },
  { id: 'AC10-coordinates-need-four-decimals', ac: 'AC10', note: 'a coordinate pair with three decimals is shown', f: sub('/(?:^|[^\\d.])-?\\d{1,3}\\.\\d{3,}\\s*[,;]\\s*-?\\d{1,3}\\.\\d{3,}(?![\\d.])/', '/(?:^|[^\\d.])-?\\d{1,3}\\.\\d{4,}\\s*[,;]\\s*-?\\d{1,3}\\.\\d{4,}(?![\\d.])/') },
  { id: 'AC10-pass-pair-dropped', ac: 'AC10', note: 'a JSON pair with a pass key, or pass=value, is shown', f: sub("['pass pair', null,", "['pass pair', 'zzzz',") },
  { id: 'AC10-pass-pair-colon-prose', ac: 'AC10', note: 'the pass-pair rule also takes plain prose such as pass: true', f: chain(sub('|(?<![a-z0-9])(?:[a-z0-9]+[_-])*(?:pass|pw)=', '|(?<![a-z0-9])(?:[a-z0-9]+[_-])*(?:pass|pw)\\s*[:=]\\s*'), sub("  'pass pair': /(?:pass|pw)(?:\\s*[\"']|=)/i,", "  'pass pair': /(?:pass|pw)/i,")) },
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

  test('mutation baseline: the unmutated copy passes the suites it is run against (the harness works)', () => {
    assert.equal(baseline.code, 0, baseline.out.slice(-2000));
  });

  for (const m of results) {
    test(`mutant ${m.id} (${m.ac}): ${m.note}: is killed`, () => {
      assert.equal(m.error, null, m.error);
      assert.notEqual(m.run.code, 0, `SURVIVED: no test failed with this break`);
    });
  }

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
    const survivors = results.filter((m) => m.error !== null || m.run.code === 0).map((m) => m.id);
    assert.deepEqual(survivors, []);
    console.log(`mutation score: ${results.length - survivors.length}/${results.length} killed; per case ${JSON.stringify(per)}`);
  });
}
