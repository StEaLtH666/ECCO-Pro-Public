/*
 * ECCO Mode Shell: one reusable per-view wrapper that gives a Home Assistant view TWO presentations of the SAME data,
 * Production Mode (calm, simple) and Geek Mode (every available non-secret data point, grouped, searchable), behind one
 * polished switch. First offline proof, built for the ECCO Intelligence SHADOW view (contract ecco-intel-entities/1).
 *
 * One dependency-free ES module: no build step, no npm packages, no network, no CDN, no web fonts, no images. Home
 * Assistant loads it as a JavaScript module resource; the node tests in ./test import the same file, so the pure core is
 * EXPORTED. Its one import-time side effect registers the custom element (guarded: only when customElements exists and the
 * tag is free) and the card-picker entry.
 *
 * What the shell is, and is not:
 *   - The mode is a PRESENTATION toggle. It is not ECCO's Manual / Assisted / Automatic authority. Switching it never starts
 *     or stops Intelligence, never enables ASSISTED or AUTONOMOUS, never writes a register or a helper, never cancels an
 *     armed session and never calls a service. The shell has NO write path: it reads hass.states (plus hass.locale and
 *     hass.themes for formatting), dispatches the standard hass-more-info event to open an entity, writes to the clipboard
 *     on a button press and offers a Blob download. Nothing else.
 *   - The mode lives ONLY in the element instance. It defaults to Production when the element is connected (and so on every
 *     reload), and it is reset to Production when the element is disconnected, when the location moves away from the path it
 *     was entered on, on pagehide and when the element becomes hidden. It is never stored (no storage API of any kind).
 *   - One adapter: buildSnapshot() turns hass.states plus the catalogue into the ONE snapshot that the alert strip, the
 *     Production summary, the Geek header, tiles and rows all read. Child cards receive the very same hass object.
 *   - Safety alerts, recovery state and owner-action-needed status are derived from the catalogue's alert list by one
 *     function (deriveAlerts) and rendered by one function (renderAlertStrip) into a strip that sits OUTSIDE both switchable
 *     bodies. Neither mode can hide it.
 *   - Honest inventory: every data point is LIVE, STALE, UNAVAILABLE, UNKNOWN, NOT_MEASURED, SIMULATED or UNVERIFIED, said in
 *     words and with an icon. A missing entity shows no value. A stale value is never shown as live.
 *   - Nothing secret or private is surfaced just because it exists: keys such as token / password / secret, JWT-like and
 *     long hex or base64 strings, URLs with credentials, IP and MAC addresses, coordinates and connection strings are
 *     replaced by a withheld marker in every row, the raw view, the search index, the copy and the export.
 *   - Every datum is rendered with textContent or a text node. innerHTML, outerHTML and insertAdjacentHTML are never used.
 *     No element, tag name or attribute NAME is ever derived from data.
 *   - The catalogue (schema ecco-geek-catalogue/1) is data, never code. New safe entities with the discover prefix appear in
 *     a Discovered group with no new hand-designed card.
 *
 * Layout of this file:
 *   1. constants, text helpers
 *   2. redaction
 *   3. catalogue and configuration validation
 *   4. classification and the snapshot (the one adapter)
 *   5. alerts and the Production summary
 *   6. search, windowing, export
 *   7. the child-card guard
 *   8. palette and style
 *   9. DOM builders and icons
 *  10. the Geek surface
 *  11. the custom element
 */

// ===========================================================================
// 1. constants, text helpers
// ===========================================================================
export const TAG = 'ecco-mode-shell';
export const VERSION = '0.1.0';
export const CATALOGUE_SCHEMA = 'ecco-geek-catalogue/1';
export const EXPORT_SCHEMA = 'ecco-geek-export/1';
export const MODES = Object.freeze(['production', 'geek']);
export const DEFAULT_MODE = 'production';
export const WITHHELD = '[withheld]';
const WITHHELD_KEY = '[withheld key';
export const STATUSES = Object.freeze(['LIVE', 'STALE', 'UNAVAILABLE', 'UNKNOWN', 'NOT_MEASURED', 'SIMULATED', 'UNVERIFIED']);
export const TICK_MS = 15000;
export const LIMITS = Object.freeze({
  value: 300, // characters of one value shown in a row
  stringCap: 4000, // characters of one string kept at all (the rest is dropped before any scan)
  dictKeys: 200, // keys of one dict kept
  listItems: 200, // items of one list kept
  attrsPerRow: 200, // attribute rows listed for one entity
  subKeys: 80, // first-level keys of one dict attribute listed as sub-rows
  depth: 8, // nesting levels walked
  nodes: 20000, // values visited in one redaction call
  rawChars: 30000, // characters of one raw view
  searchChars: 6000, // characters of one row's search text
  pageSize: 25,
  maxPageSize: 100,
  tiles: 12,
});
/** Test hook: counters of work done (not state that affects behaviour). */
export const STATS = { partsBuilt: 0, snapshots: 0 };

const PRIORITIES = Object.freeze(['headline', 'normal', 'obscure']);
const PRIORITY_RANK = Object.freeze({ headline: 0, normal: 1, obscure: 2 });
const ORIGINS = Object.freeze(['integration', 'package', 'dashboard']);
const SEVERITIES = Object.freeze(['critical', 'warning', 'info']);
const SEVERITY_RANK = Object.freeze({ critical: 0, warning: 1, info: 2 });
const EXCEPTION_REASONS = Object.freeze(['secret', 'privacy', 'unsupported_source', 'not_exposed_in_states']);

const isObj = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const isStr = (v) => typeof v === 'string';
const isNum = (v) => typeof v === 'number' && Number.isFinite(v);
const hasOwn = (o, k) => Object.prototype.hasOwnProperty.call(o, k);

// Control, zero-width, bidirectional and invisible-format characters are shown as visible escapes, never raw. Tab, newline
// and carriage return are kept (the raw view is pre-wrapped text).
const CTRL = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\u00ad\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff]/g;

/** Text that is safe to show: control characters escaped, long text truncated with a visible marker. */
export function cleanText(v, max = LIMITS.value) {
  let s = isStr(v) ? v : String(v);
  let cut = 0;
  if (s.length > max) {
    cut = s.length - max;
    s = s.slice(0, max);
  }
  s = s.replace(CTRL, (c) => `\u2039U+${c.charCodeAt(0).toString(16).toUpperCase().padStart(4, '0')}\u203a`);
  return cut ? `${s}\u2026 [truncated ${cut} more characters]` : s;
}

/** "5 min ago": plain words, no invented precision. */
export function formatAge(s) {
  if (!isNum(s) || s < 0) return 'age unknown';
  if (s < 5) return 'just now';
  if (s < 60) return `${Math.round(s)} s ago`;
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) {
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    return m ? `${h} h ${m} min ago` : `${h} h ago`;
  }
  return `${Math.floor(s / 86400)} d ago`;
}

function parseTime(v) {
  if (!isStr(v)) return null;
  const t = Date.parse(v);
  return Number.isFinite(t) ? t : null;
}

// ===========================================================================
// 2. redaction
// ===========================================================================
// KEY rules: a key whose words say "secret" or "private" withholds its whole value, whatever the value looks like.
const SECRET_TOKENS = new Set(['token', 'tokens', 'password', 'passwords', 'passwd', 'pwd', 'passphrase', 'passcode', 'pincode', 'secret', 'secrets',
  'apikey', 'apikeys', 'authorization', 'auth', 'bearer', 'credential', 'credentials', 'privatekey', 'webhook', 'webhooks', 'cookie', 'cookies',
  'session', 'sessions', 'psk', 'dsn', 'otp', 'jwt', 'signature', 'accesskey', 'secretkey', 'signingkey', 'clientsecret', 'connectionstring',
  'connstr', 'refreshtoken']);
const PRIVATE_TOKENS = new Set(['latitude', 'longitude', 'lat', 'lon', 'lng', 'location', 'locations', 'gps', 'coordinates', 'coordinate', 'address',
  'addresses', 'email', 'emails', 'phone', 'postcode', 'postal', 'ssid', 'bssid', 'mac', 'ip', 'hostname', 'serial', 'serialnumber', 'mpan', 'mprn',
  'imei', 'username', 'account', 'accountid', 'meterid']);
// Keys that hold a public source revision: a 40-hex git object name is shown under these keys only.
const DIGEST_KEYS = new Set(['gitsha', 'commit', 'commitsha', 'gitcommit']);

function keyTokens(key) {
  return String(key).replace(/([a-z0-9])([A-Z])/g, '$1 $2').toLowerCase().split(/[^a-z0-9]+/).filter(Boolean);
}

const EXTRA_CACHE = new WeakMap();
/** Catalogue extra_key_patterns -> safe RegExps. A pattern that is too long, shaped for catastrophic backtracking or invalid is ignored. */
function compileExtra(list) {
  if (!Array.isArray(list)) return [];
  if (EXTRA_CACHE.has(list)) return EXTRA_CACHE.get(list);
  const out = [];
  for (const src of list.slice(0, 40)) {
    if (!isStr(src) || src.length === 0 || src.length > 80) continue;
    if (/\([^)]*[+*][^)]*\)\s*[+*{]/.test(src) || /\\[1-9]/.test(src)) continue;
    try {
      out.push(new RegExp(src, 'i'));
    } catch {
      // an invalid pattern is ignored, never fatal
    }
  }
  EXTRA_CACHE.set(list, out);
  return out;
}

function isSecretKey(key, extra) {
  const tokens = keyTokens(key);
  for (let i = 0; i < tokens.length; i += 1) {
    if (SECRET_TOKENS.has(tokens[i]) || PRIVATE_TOKENS.has(tokens[i])) return true;
    if (i + 1 < tokens.length) {
      const pair = tokens[i] + tokens[i + 1];
      if (SECRET_TOKENS.has(pair) || PRIVATE_TOKENS.has(pair)) return true;
    }
  }
  const compact = tokens.join('');
  if (SECRET_TOKENS.has(compact) || PRIVATE_TOKENS.has(compact)) return true;
  const k = String(key);
  for (const re of extra) if (re.test(k)) return true;
  return false;
}

// VALUE rules: [reason, required substring or null, pattern]. The gates keep the common case (short plain strings) cheap.
const RULES = [
  ['jwt', 'eyJ', /\beyJ[\w-]{4,}\.[\w-]{4,}\.[\w-]*/],
  ['key block', '-----', /-----BEGIN [A-Z0-9 ]+-----/],
  ['url credentials', '@', /\b[a-z][a-z0-9+.-]*:\/\/[^\s/?#@]*@/i],
  ['connection string', '://', /\b(?:postgres(?:ql)?|mysql|mariadb|mongodb(?:\+srv)?|redis|rediss|amqps?|mqtts?|influxdb|mssql|sqlserver|jdbc|ftps?|sftp|ssh|smb|ldaps?|couchdb)(?::[a-z0-9]+)?:\/\//i],
  ['url token', '=', /[?&#;][\w.%-]*(?:token|secret|passw|pwd|apikey|api[_-]?key|auth|sig|signature|credential|session|bearer|jwt|key)[\w.%-]*=[^&\s]{3,}/i],
  ['credential pair', null, /\b(?:password|passwd|pwd|secret|token|api[_-]?key|apikey|authorization)\b\s*[:=]\s*[^\s,;]{3,}/i],
  ['connection pairs', ';', /\b(?:server|data source|host|hostname|uid|user ?id|userid|pwd|password|database|initial catalog)\s*=\s*[^;\s]+\s*;/i],
  ['bearer', null, /\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,}/i],
  ['known token', null, /\b(?:gh[pousr]_[A-Za-z0-9]{20,}|xox[abprs]-[A-Za-z0-9-]{10,}|sk_(?:live|test)_[A-Za-z0-9]{10,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|glpat-[A-Za-z0-9_-]{20,})/],
  ['email address', '@', /\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b/],
  ['IPv4 address', '.', /\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b/],
  ['IPv6 address', ':', /(?:^|[^0-9a-fA-F:])(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}(?![0-9a-fA-F:])|(?:^|[^0-9a-zA-Z:])(?:[0-9a-fA-F]{1,4}:){0,6}[0-9a-fA-F]{1,4}?::(?:[0-9a-fA-F]{1,4}(?::[0-9a-fA-F]{1,4}){0,6})?(?![0-9a-zA-Z:])/],
  ['MAC address', null, /\b(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}\b/],
  ['coordinates', null, /(?:^|[^\d.])-?\d{1,3}\.\d{4,}\s*[,;]\s*-?\d{1,3}\.\d{4,}(?![\d.])/],
  ['private host name', '.', /\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:local|lan|internal|home\.arpa|localdomain)\b/i],
];
const RE_HEX = /(?:^|[^0-9a-fA-F])[0-9a-fA-F]{32,}(?![0-9a-fA-F])/;
const RE_B64 = /[A-Za-z0-9+/_-]{32,}={0,2}/g;
const RE_GIT = /^[0-9a-f]{40}$/i;

/** Why a string looks secret or private, or null. */
function valueReason(s, digestOk) {
  if (s.length < 6) return null;
  for (const [reason, gate, re] of RULES) {
    if (gate !== null && !s.includes(gate)) continue;
    if (re.test(s)) return reason;
  }
  if (s.length >= 32) {
    if (!digestOk && RE_HEX.test(s)) return 'long hex value';
    for (const t of s.match(RE_B64) || []) if (/[A-Z]/.test(t) && /[a-z]/.test(t) && /[0-9]/.test(t)) return 'long encoded value';
  }
  return null;
}

function redactString(s, key) {
  const k = key === null ? '' : keyTokens(key).join('');
  const digestOk = DIGEST_KEYS.has(k) && RE_GIT.test(s);
  let t = s;
  let cut = 0;
  if (t.length > LIMITS.stringCap) {
    cut = t.length - LIMITS.stringCap;
    t = t.slice(0, LIMITS.stringCap);
  }
  if (valueReason(t, digestOk) !== null) return WITHHELD;
  return cut ? `${cleanText(t, LIMITS.stringCap)}\u2026 [truncated ${cut} more characters]` : cleanText(t, LIMITS.stringCap);
}

function redactNode(v, key, ctx, depth) {
  ctx.budget.n -= 1;
  if (ctx.budget.n < 0) return '[more values omitted]';
  if (v === null || v === undefined) return null;
  if (key !== null && isSecretKey(key, ctx.extra)) return WITHHELD;
  const t = typeof v;
  if (t === 'string') return redactString(v, key);
  if (t === 'number') return Number.isFinite(v) ? v : String(v);
  if (t === 'boolean') return v;
  if (t === 'bigint') return String(v);
  if (t !== 'object') return `[${t}]`;
  if (depth >= LIMITS.depth) return '[nested too deep]';
  if (Array.isArray(v)) {
    const out = [];
    const n = Math.min(v.length, LIMITS.listItems);
    for (let i = 0; i < n; i += 1) out.push(redactNode(v[i], key, ctx, depth + 1));
    if (v.length > n) out.push(`\u2026 ${v.length - n} more items`);
    return out;
  }
  const out = {};
  const keys = Object.keys(v);
  let i = 0;
  for (const k of keys) {
    if (i >= LIMITS.dictKeys) {
      out['\u2026'] = `${keys.length - i} more keys`;
      break;
    }
    i += 1;
    let shown;
    if (k === '__proto__') shown = '[__proto__]';
    else if (valueReason(k.length > 200 ? k.slice(0, 200) : k, false) !== null) {
      ctx.keyCount += 1;
      shown = `${WITHHELD_KEY} ${ctx.keyCount}]`;
    } else shown = cleanText(k, 120);
    out[shown] = redactNode(v[k], k, ctx, depth + 1);
  }
  return out;
}

const newCtx = (opts) => ({
  extra: opts && Array.isArray(opts.extraKeyPatterns) ? compileExtra(opts.extraKeyPatterns) : [],
  budget: { n: LIMITS.nodes },
  keyCount: 0,
});

/** A redacted deep copy of any value. opts.key is the key the value sits under; opts.extraKeyPatterns the catalogue's patterns. */
export function redactValue(value, opts = {}) {
  return redactNode(value, isStr(opts.key) ? opts.key : null, newCtx(opts), 0);
}

/** A redacted deep copy of an attribute object. */
export function redactAttributes(attrs, opts = {}) {
  if (!isObj(attrs)) return {};
  return redactNode(attrs, null, newCtx(opts), 0);
}

/** How many withheld markers (values and key names) a redacted structure holds. */
export function countWithheld(v) {
  if (v === WITHHELD) return 1;
  if (Array.isArray(v)) return v.reduce((n, x) => n + countWithheld(x), 0);
  if (isObj(v)) {
    let n = 0;
    for (const k of Object.keys(v)) n += (k.startsWith(WITHHELD_KEY) ? 1 : 0) + countWithheld(v[k]);
    return n;
  }
  return 0;
}

// ===========================================================================
// 3. catalogue and configuration validation
// ===========================================================================
const err = (errors, path, message) => errors.push({ path, message });

function validAttr(a, path, errors) {
  if (!isObj(a)) {
    err(errors, path, 'attribute entry must be an object');
    return null;
  }
  if (!isStr(a.name) || a.name === '' || a.name.length > 120 || a.name.startsWith('.') || a.name.endsWith('.')) {
    err(errors, `${path}.name`, 'attribute name must be a non-empty string (a dotted path reaches into a dict attribute)');
    return null;
  }
  const priority = a.priority === undefined ? 'normal' : a.priority;
  if (!PRIORITIES.includes(priority)) {
    err(errors, `${path}.priority`, 'priority must be headline, normal or obscure');
    return null;
  }
  return {
    name: a.name,
    description: isStr(a.description) ? cleanText(a.description, 600) : '',
    unit: isStr(a.unit) ? cleanText(a.unit, 20) : null,
    priority,
  };
}

function validSource(s, i, groupIds, errors) {
  const path = `sources[${i}]`;
  const before = errors.length;
  if (!isObj(s)) {
    err(errors, path, 'source must be an object');
    return null;
  }
  for (const k of ['id', 'entity_id', 'group', 'title']) if (!isStr(s[k]) || s[k] === '') err(errors, `${path}.${k}`, `${k} must be a non-empty string`);
  if (isStr(s.entity_id) && !/^[a-z0-9_]+\.[a-z0-9_]+$/.test(s.entity_id)) err(errors, `${path}.entity_id`, 'entity_id must look like domain.object_id');
  if (isStr(s.group) && !groupIds.has(s.group)) err(errors, `${path}.group`, 'group is not defined in groups');
  if (!PRIORITIES.includes(s.priority)) err(errors, `${path}.priority`, 'priority must be headline, normal or obscure');
  if (!ORIGINS.includes(s.origin)) err(errors, `${path}.origin`, 'origin must be integration, package or dashboard');
  for (const k of ['expected_update_s', 'stale_after_s']) {
    if (s[k] !== null && s[k] !== undefined && !(isNum(s[k]) && s[k] >= 0)) err(errors, `${path}.${k}`, `${k} must be a number >= 0 or null`);
  }
  if (s.unit !== null && s.unit !== undefined && !isStr(s.unit)) err(errors, `${path}.unit`, 'unit must be a string or null');
  const attributes = [];
  if (s.attributes !== undefined && !Array.isArray(s.attributes)) err(errors, `${path}.attributes`, 'attributes must be a list');
  else (s.attributes || []).forEach((a, j) => {
    const v = validAttr(a, `${path}.attributes[${j}]`, errors);
    if (v) attributes.push(v);
  });
  if (errors.length > before) return null;
  return {
    id: s.id, entity_id: s.entity_id, group: s.group, title: cleanText(s.title, 200),
    description: isStr(s.description) ? cleanText(s.description, 600) : '', priority: s.priority,
    unit: isStr(s.unit) ? cleanText(s.unit, 20) : null,
    expected_update_s: isNum(s.expected_update_s) ? s.expected_update_s : null,
    stale_after_s: isNum(s.stale_after_s) ? s.stale_after_s : null, origin: s.origin, attributes,
  };
}

function validWhen(w) {
  if (!isObj(w)) return null;
  if (w.unavailable === true) return { unavailable: true };
  if (Array.isArray(w.state_in) && w.state_in.every(isStr)) return { state_in: w.state_in.slice(0, 50) };
  if (Array.isArray(w.state_not_in) && w.state_not_in.every(isStr)) return { state_not_in: w.state_not_in.slice(0, 50) };
  if (isStr(w.attribute) && w.attribute !== '' && Array.isArray(w.in) && w.in.every(isStr)) return { attribute: w.attribute, in: w.in.slice(0, 50) };
  return null;
}

function validAlert(a, i, errors) {
  const path = `alerts[${i}]`;
  if (!isObj(a)) {
    err(errors, path, 'alert must be an object');
    return null;
  }
  const before = errors.length;
  for (const k of ['id', 'entity_id', 'text', 'action']) if (!isStr(a[k]) || a[k] === '') err(errors, `${path}.${k}`, `${k} must be a non-empty string`);
  if (!SEVERITIES.includes(a.severity)) err(errors, `${path}.severity`, 'severity must be critical, warning or info');
  const when = validWhen(a.when);
  if (!when) err(errors, `${path}.when`, 'when must be one of unavailable, state_in, state_not_in or attribute + in');
  if (errors.length > before) return null;
  return { id: a.id, severity: a.severity, entity_id: a.entity_id, when, text: cleanText(a.text, 300), action: cleanText(a.action, 300) };
}

const emptyCatalogue = () => ({
  schema: CATALOGUE_SCHEMA, view_id: '', title: '', contract: '', groups: [], sources: [],
  discover: { entity_prefixes: [], group: 'discovered', exclude_entity_ids: [] }, alerts: [], exceptions: [], redaction: { extra_key_patterns: [] },
});

/**
 * Validate a catalogue (schema ecco-geek-catalogue/1). Never throws. Returns { ok, errors: [{path, message}], catalogue } where
 * `catalogue` is a sanitised copy: unknown keys dropped, every string capped. The alerts that are individually valid are
 * ALWAYS kept (the safety strip must not depend on the rest being right); sources are kept only when the schema is known.
 * `ok` is false on any problem, and the shell then switches the inventory off (it fails closed) and says why.
 */
export function validateCatalogue(input) {
  const errors = [];
  const out = emptyCatalogue();
  if (!isObj(input)) {
    err(errors, 'catalogue', 'the catalogue is missing or is not an object');
    return { ok: false, errors, catalogue: out };
  }
  const schemaOk = input.schema === CATALOGUE_SCHEMA;
  if (!schemaOk) err(errors, 'schema', `unknown catalogue schema ${isStr(input.schema) ? cleanText(input.schema, 60) : '(none)'}, expected ${CATALOGUE_SCHEMA}`);
  for (const k of ['view_id', 'title', 'contract']) {
    if (isStr(input[k])) out[k] = cleanText(input[k], 200);
    else err(errors, k, `${k} must be a string`);
  }
  const groupIds = new Set();
  if (Array.isArray(input.groups)) {
    input.groups.forEach((g, i) => {
      if (!isObj(g) || !isStr(g.id) || g.id === '' || !isStr(g.title) || !isNum(g.order)) {
        err(errors, `groups[${i}]`, 'group needs id, title and a numeric order');
      } else if (groupIds.has(g.id)) err(errors, `groups[${i}].id`, 'duplicate group id');
      else {
        groupIds.add(g.id);
        out.groups.push({ id: g.id, title: cleanText(g.title, 120), order: g.order, description: isStr(g.description) ? cleanText(g.description, 400) : '' });
      }
    });
  } else err(errors, 'groups', 'groups must be a list');
  const sources = [];
  if (Array.isArray(input.sources)) {
    const seen = new Set();
    input.sources.forEach((s, i) => {
      const v = validSource(s, i, groupIds, errors);
      if (!v) return;
      if (seen.has(v.id)) {
        err(errors, `sources[${i}].id`, 'duplicate source id');
        return;
      }
      seen.add(v.id);
      sources.push(v);
    });
  } else err(errors, 'sources', 'sources must be a list');
  if (isObj(input.discover)) {
    const d = input.discover;
    const prefixes = Array.isArray(d.entity_prefixes) ? d.entity_prefixes : null;
    if (!prefixes || !prefixes.every((p) => isStr(p) && /^[a-z_]+\.[a-z0-9_]*$/.test(p))) err(errors, 'discover.entity_prefixes', 'entity_prefixes must be a list of domain.prefix strings');
    else out.discover.entity_prefixes = prefixes.slice(0, 20);
    if (d.group !== undefined && (!isStr(d.group) || d.group === '')) err(errors, 'discover.group', 'group must be a non-empty string');
    else if (isStr(d.group)) out.discover.group = d.group;
    if (Array.isArray(d.exclude_entity_ids) && d.exclude_entity_ids.every(isStr)) out.discover.exclude_entity_ids = d.exclude_entity_ids.slice(0, 500);
    else if (d.exclude_entity_ids !== undefined) err(errors, 'discover.exclude_entity_ids', 'exclude_entity_ids must be a list of strings');
  } else if (input.discover !== undefined) err(errors, 'discover', 'discover must be an object');
  if (Array.isArray(input.alerts)) {
    const seen = new Set();
    input.alerts.forEach((a, i) => {
      const v = validAlert(a, i, errors);
      if (!v) return;
      if (seen.has(v.id)) {
        err(errors, `alerts[${i}].id`, 'duplicate alert id');
        return;
      }
      seen.add(v.id);
      out.alerts.push(v);
    });
  } else err(errors, 'alerts', 'alerts must be a list');
  if (Array.isArray(input.exceptions)) {
    input.exceptions.forEach((x, i) => {
      if (!isObj(x) || !isStr(x.id) || !isStr(x.what) || !EXCEPTION_REASONS.includes(x.reason)) {
        err(errors, `exceptions[${i}]`, 'exception needs id, what and a reason (secret, privacy, unsupported_source, not_exposed_in_states)');
      } else out.exceptions.push({ id: x.id, what: cleanText(x.what, 200), reason: x.reason, note: isStr(x.note) ? cleanText(x.note, 400) : '' });
    });
  } else if (input.exceptions !== undefined) err(errors, 'exceptions', 'exceptions must be a list');
  if (isObj(input.redaction) && Array.isArray(input.redaction.extra_key_patterns)) {
    out.redaction.extra_key_patterns = input.redaction.extra_key_patterns.filter(isStr).slice(0, 40);
  } else if (input.redaction !== undefined && !isObj(input.redaction)) err(errors, 'redaction', 'redaction must be an object');
  if (schemaOk) out.sources = sources;
  return { ok: errors.length === 0, errors, catalogue: out };
}

/** The shell's own configuration. Never throws; unknown keys are tolerated; problems are listed. */
export function validateConfig(config) {
  const errors = [];
  const c = isObj(config) ? config : {};
  if (!isObj(config)) err(errors, 'config', 'the card configuration must be an object');
  const list = (k) => {
    if (c[k] === undefined) return [];
    if (Array.isArray(c[k])) return c[k];
    err(errors, k, `${k} must be a list of card configurations`);
    return [];
  };
  let pageSize = LIMITS.pageSize;
  if (c.page_size !== undefined) {
    if (Number.isInteger(c.page_size) && c.page_size >= 5 && c.page_size <= LIMITS.maxPageSize) pageSize = c.page_size;
    else err(errors, 'page_size', `page_size must be a whole number from 5 to ${LIMITS.maxPageSize}`);
  }
  if (c.alerts_from !== undefined && c.alerts_from !== 'catalogue') err(errors, 'alerts_from', 'only alerts_from: catalogue is supported');
  return {
    viewId: isStr(c.view_id) ? cleanText(c.view_id, 80) : null, title: isStr(c.title) ? cleanText(c.title, 120) : null,
    catalogue: c.catalogue, always: list('always'), production: list('production'), pageSize, errors,
  };
}

// ===========================================================================
// 4. classification and the snapshot (the one adapter)
// ===========================================================================
const SIM_RE = /^(?:simulated|synthetic)/i;
const isSimulated = (a) => a.simulated === true || a.is_simulated === true || a.synthetic === true || (isStr(a.provenance) && SIM_RE.test(a.provenance))
  || (isStr(a.data_source) && SIM_RE.test(a.data_source)) || (isStr(a.source_kind) && SIM_RE.test(a.source_kind));
const isUnverified = (a) => a.verified === false || a.unverified === true || a.provenance_ok === false || (isStr(a.provenance) && /^unverified/i.test(a.provenance));

/**
 * The honest status of one data point. A missing entity is NOT_MEASURED (never a value); unavailable and unknown outrank
 * everything; a source with a freshness rule (stale_after_s) is STALE past it, and cannot be called LIVE if it has no usable
 * timestamp (UNVERIFIED); simulated and unverified are attribute flags. `flags` lists every status that applies, the primary
 * one first; a STALE row is never also LIVE.
 */
export function classifyRow(source, state, nowMs) {
  const src = isObj(source) ? source : {};
  if (!isObj(state)) return { status: 'NOT_MEASURED', flags: ['NOT_MEASURED'], ageS: null, lastUpdatedMs: null, ageMonitored: false };
  const lu = parseTime(state.last_updated) !== null ? parseTime(state.last_updated) : parseTime(state.last_changed);
  const ageS = lu === null ? null : Math.max(0, (nowMs - lu) / 1000);
  const limit = isNum(src.stale_after_s) && src.stale_after_s > 0 ? src.stale_after_s : null;
  const done = (status, flags) => ({ status, flags, ageS, lastUpdatedMs: lu, ageMonitored: limit !== null });
  const sv = state.state === null || state.state === undefined ? 'unknown' : String(state.state);
  if (sv === 'unavailable') return done('UNAVAILABLE', ['UNAVAILABLE']);
  if (sv === 'unknown' || sv === '') return done('UNKNOWN', ['UNKNOWN']);
  const attrs = isObj(state.attributes) ? state.attributes : {};
  const stale = limit !== null && ageS !== null && ageS > limit;
  const sim = isSimulated(attrs);
  const unv = (limit !== null && ageS === null) || isUnverified(attrs);
  const flags = STATUSES.filter((s) => (s === 'STALE' && stale) || (s === 'SIMULATED' && sim) || (s === 'UNVERIFIED' && unv));
  if (flags.length === 0) return done('LIVE', ['LIVE']);
  return done(flags[0], flags);
}

const PREP = new WeakMap();
/** The catalogue as the snapshot uses it: ordered groups, source lookups, compiled patterns. Cached per catalogue object. */
function prepare(catalogue) {
  const key = isObj(catalogue) ? catalogue : null;
  if (key && PREP.has(key)) return PREP.get(key);
  const c = key || emptyCatalogue();
  const sources = Array.isArray(c.sources) ? c.sources.filter(isObj) : [];
  const d = isObj(c.discover) ? c.discover : {};
  const prefixes = Array.isArray(d.entity_prefixes) ? d.entity_prefixes.filter(isStr) : [];
  const discoverGroup = isStr(d.group) && d.group !== '' ? d.group : 'discovered';
  const groups = (Array.isArray(c.groups) ? c.groups : []).filter((g) => isObj(g) && isStr(g.id)).map((g, i) => ({
    id: g.id, title: isStr(g.title) ? g.title : g.id, order: isNum(g.order) ? g.order : i, description: isStr(g.description) ? g.description : '',
  }));
  if (prefixes.length && !groups.some((g) => g.id === discoverGroup)) {
    groups.push({ id: discoverGroup, title: 'Discovered', order: 1e6, description: 'Entities with a discovery prefix that the catalogue does not describe yet.' });
  }
  for (const s of sources) if (isStr(s.group) && !groups.some((g) => g.id === s.group)) groups.push({ id: s.group, title: s.group, order: 1e6 + 1, description: '' });
  groups.sort((a, b) => a.order - b.order);
  const prepared = {
    src: c, viewId: isStr(c.view_id) ? c.view_id : '', title: isStr(c.title) ? c.title : '', contract: isStr(c.contract) ? c.contract : '', groups,
    groupOrder: new Map(groups.map((g, i) => [g.id, i])), sources, claimed: new Set(sources.map((s) => s.entity_id)),
    discover: { prefixes, group: discoverGroup, exclude: new Set(Array.isArray(d.exclude_entity_ids) ? d.exclude_entity_ids.filter(isStr) : []) },
    extraPatterns: isObj(c.redaction) && Array.isArray(c.redaction.extra_key_patterns) ? c.redaction.extra_key_patterns : [],
    alerts: Array.isArray(c.alerts) ? c.alerts : [], exceptions: Array.isArray(c.exceptions) ? c.exceptions : [],
  };
  if (key) PREP.set(key, prepared);
  return prepared;
}

const DISCOVERED = { discovered: true };
const PARTS = new WeakMap();
const SEQ = { parts: 0 };

const kindOf = (v) => (v === null ? 'null' : Array.isArray(v) ? 'list' : typeof v === 'object' ? 'dict' : typeof v);

/** The display text of one (already redacted) value. */
function showValue(v) {
  if (v === null || v === undefined) return 'null';
  if (typeof v === 'string') return cleanText(v, LIMITS.value);
  if (Array.isArray(v)) {
    if (v.length === 0) return '[]';
    if (v.length <= 6 && v.every((x) => x === null || ['string', 'number', 'boolean'].includes(typeof x))) {
      const text = `[${v.map((x) => (x === null ? 'null' : String(x))).join(', ')}]`;
      if (text.length <= 100) return cleanText(text, LIMITS.value);
    }
    return `[${v.length} items]`;
  }
  if (typeof v === 'object') {
    const n = Object.keys(v).length;
    return n === 0 ? '{}' : `{${n} keys}`;
  }
  return String(v);
}

function attrRow(path, name, parent, depth, decl, present, value) {
  const text = present ? showValue(value) : 'Not present';
  return {
    path, name, parent, depth, declared: decl !== null, present, kind: present ? kindOf(value) : 'absent', value: text,
    description: decl ? decl.description : '', unit: decl ? decl.unit : null, priority: decl ? decl.priority : 'normal',
    withheld: present && value === WITHHELD, truncated: present && text.includes('[truncated'),
  };
}

/** The attribute rows of one entity: declared first (present or honestly absent), then every other attribute; dict attributes get sub-rows. */
function describeAttributes(red, declaredList) {
  const decl = new Map(declaredList.map((a) => [a.name, a]));
  const tops = [];
  const topSeen = new Set();
  for (const a of declaredList) {
    const top = a.name.split('.')[0];
    if (!topSeen.has(top)) {
      topSeen.add(top);
      tops.push(top);
    }
  }
  const extras = Object.keys(red).filter((k) => !topSeen.has(k)).sort();
  const rows = [];
  for (const top of [...tops, ...extras]) {
    const present = hasOwn(red, top);
    const value = present ? red[top] : undefined;
    rows.push(attrRow(top, top, null, 0, decl.get(top) || null, present, value));
    if (!present || !isObj(value)) {
      for (const a of declaredList) if (a.name.startsWith(`${top}.`)) rows.push(attrRow(a.name, a.name.slice(top.length + 1), top, 1, a, false, undefined));
      continue;
    }
    const subs = [];
    const seen = new Set();
    for (const a of declaredList) {
      if (!a.name.startsWith(`${top}.`)) continue;
      const rest = a.name.slice(top.length + 1);
      seen.add(rest);
      const has = hasOwn(value, rest);
      subs.push(attrRow(a.name, rest, top, rest.split('.').length, a, has, has ? value[rest] : undefined));
    }
    const others = Object.keys(value).filter((k) => !seen.has(k)).sort();
    for (const k of others.slice(0, LIMITS.subKeys)) subs.push(attrRow(`${top}.${k}`, k, top, 1, decl.get(`${top}.${k}`) || null, true, value[k]));
    if (others.length > LIMITS.subKeys) subs.push(attrRow(`${top}.\u2026`, `\u2026 ${others.length - LIMITS.subKeys} more keys`, top, 1, null, true, 'see the raw view'));
    rows.push(...subs);
  }
  return rows;
}

function flattenForSearch(v, out, budget) {
  if (budget.n <= 0) return;
  if (v === null || v === undefined) return;
  if (typeof v === 'string') {
    out.push(v);
    budget.n -= v.length;
  } else if (typeof v === 'number' || typeof v === 'boolean') {
    out.push(String(v));
    budget.n -= 6;
  } else if (Array.isArray(v)) v.slice(0, 40).forEach((x) => flattenForSearch(x, out, budget));
  else if (typeof v === 'object') {
    for (const k of Object.keys(v).slice(0, 60)) {
      out.push(k);
      budget.n -= k.length;
      flattenForSearch(v[k], out, budget);
    }
  }
}

/** The part of a row that depends only on the state object (cached per state object: Home Assistant replaces it on any change). */
function partsFor(source, state, cat) {
  const ref = source.discovered ? DISCOVERED : source;
  const hit = PARTS.get(state);
  if (hit && hit.cat === cat && hit.ref === ref) return hit;
  STATS.partsBuilt += 1;
  const attrsRaw = isObj(state.attributes) ? state.attributes : {};
  const opts = { extraKeyPatterns: cat.extraPatterns };
  const red = redactAttributes(attrsRaw, opts);
  const stateStr = state.state === null || state.state === undefined ? '' : String(state.state);
  const stateRed = redactValue(stateStr, opts);
  const declared = source.attributes || [];
  let rows = describeAttributes(red, declared);
  const total = Object.keys(attrsRaw).length;
  if (rows.length > LIMITS.attrsPerRow) {
    const more = rows.length - LIMITS.attrsPerRow;
    rows = rows.slice(0, LIMITS.attrsPerRow);
    rows.push(attrRow('\u2026', `\u2026 ${more} more attributes`, null, 0, null, true, 'see the raw view'));
  }
  const unitRaw = isStr(attrsRaw.unit_of_measurement) ? redactValue(attrsRaw.unit_of_measurement, opts) : '';
  const friendly = isStr(attrsRaw.friendly_name) ? redactValue(attrsRaw.friendly_name, { ...opts, key: 'note' }) : '';
  const bits = [];
  flattenForSearch(red, bits, { n: LIMITS.searchChars });
  const parts = {
    cat, ref, id: (SEQ.parts += 1), red, stateStr: stateRed, attrRows: rows, attrTotal: total, unit: isStr(unitRaw) && unitRaw !== WITHHELD ? unitRaw : '',
    friendly: isStr(friendly) ? friendly : '', bits: bits.join(' ').slice(0, LIMITS.searchChars), withheld: countWithheld(red) + (stateRed === WITHHELD ? 1 : 0),
  };
  PARTS.set(state, parts);
  return parts;
}

const EMPTY_ATTRS = (declared) => declared.map((a) => attrRow(a.name, a.name.includes('.') ? a.name.slice(a.name.indexOf('.') + 1) : a.name,
  a.name.includes('.') ? a.name.split('.')[0] : null, a.name.includes('.') ? 1 : 0, a, false, undefined));

function makeRow(source, state, nowMs, cat, order, ledgerKey) {
  const present = isObj(state);
  const cls = classifyRow(source, present ? state : null, nowMs);
  const parts = present ? partsFor(source, state, cat) : null;
  const unitFromSource = source.unit || '';
  const unitText = present && cls.status !== 'UNAVAILABLE' && cls.status !== 'UNKNOWN' ? (unitFromSource || (parts.unit || '')) : '';
  let stateText;
  if (cls.status === 'NOT_MEASURED') stateText = 'Not measured';
  else if (cls.status === 'UNAVAILABLE') stateText = 'Unavailable';
  else if (cls.status === 'UNKNOWN') stateText = 'Unknown';
  else stateText = parts.stateStr;
  const showUnit = stateText !== WITHHELD ? unitText : '';
  const attributes = present ? parts.attrRows : EMPTY_ATTRS(source.attributes || []);
  const ageText = cls.status === 'NOT_MEASURED' ? 'no data' : formatAge(cls.ageS);
  const title = source.discovered ? (parts.friendly && parts.friendly !== WITHHELD ? parts.friendly : '') || ledgerKey.display : source.title;
  const search = [ledgerKey.display, source.id, title, source.description || '', stateText, showUnit, parts ? parts.bits : '', ...attributes.map((a) => a.path)]
    .join(' ').toLowerCase();
  return {
    key: ledgerKey.key, id: ledgerKey.id, entity_id: ledgerKey.display, title, description: source.description || '', group: source.group,
    priority: source.priority, unit: source.unit || null, origin: source.origin, discovered: !!source.discovered, status: cls.status, flags: cls.flags,
    ageS: cls.ageS, ageText, lastUpdated: cls.lastUpdatedMs, ageMonitored: cls.ageMonitored, present, stateText, unitText: showUnit,
    expected_update_s: source.expected_update_s === undefined ? null : source.expected_update_s,
    stale_after_s: source.stale_after_s === undefined ? null : source.stale_after_s, attributes, attrTotal: present ? parts.attrTotal : attributes.length,
    searchText: search, problem: cls.status !== 'LIVE', redacted: present ? parts.red : {},
    withheld: (parts ? parts.withheld : 0) + (ledgerKey.display === WITHHELD ? 1 : 0) + (title === WITHHELD ? 1 : 0),
    sig: [cls.status, cls.flags.join(','), stateText, showUnit, ageText, cls.ageMonitored ? 'm' : 'u', parts ? parts.id : 0, ledgerKey.display].join('\u0001'),
    order,
  };
}

/**
 * THE ADAPTER. hass.states + the catalogue + a clock -> one snapshot: a row per catalogue source (in group / priority /
 * catalogue order) plus a row per discovered entity (a catalogue discover prefix that no source claims), the group list, the
 * status counts and the alert inputs. Everything that is shown anywhere in the shell comes from this object. Total: any
 * shape of states or catalogue gives a snapshot, never an exception.
 */
export function buildSnapshot(states, catalogue, nowMs) {
  STATS.snapshots += 1;
  const st = isObj(states) ? states : {};
  const cat = prepare(catalogue);
  const rows = [];
  cat.sources.forEach((src, i) => {
    rows.push(makeRow(src, st[src.entity_id], nowMs, cat, i, { key: `src:${src.id}`, id: src.id, display: cleanText(src.entity_id, 200) }));
  });
  if (cat.discover.prefixes.length) {
    const found = [];
    for (const id of Object.keys(st)) {
      if (cat.claimed.has(id) || cat.discover.exclude.has(id)) continue;
      for (const p of cat.discover.prefixes) {
        if (id.startsWith(p)) {
          found.push(id);
          break;
        }
      }
    }
    found.sort();
    let withheldN = 0;
    found.forEach((id, i) => {
      const state = st[id];
      const shown = redactString(id, 'note');
      const display = shown === WITHHELD ? WITHHELD : shown;
      if (display === WITHHELD) withheldN += 1;
      const tag = display === WITHHELD ? `withheld-${withheldN}` : display;
      const src = { id: `discovered:${tag}`, entity_id: id, group: cat.discover.group, title: display, description: 'Found by its entity prefix. The catalogue does not describe it yet.',
        priority: 'normal', unit: null, expected_update_s: null, stale_after_s: null, origin: 'discovered', attributes: [], discovered: true };
      rows.push(makeRow(src, state, nowMs, cat, 1e6 + i, { key: `disc:${tag}`, id: `discovered:${tag}`, display }));
    });
  }
  rows.sort((a, b) => (cat.groupOrder.has(a.group) ? cat.groupOrder.get(a.group) : 1e6) - (cat.groupOrder.has(b.group) ? cat.groupOrder.get(b.group) : 1e6)
    || PRIORITY_RANK[a.priority] - PRIORITY_RANK[b.priority] || a.order - b.order);
  const counts = { total: rows.length, withheld: 0, discovered: 0, problems: 0 };
  for (const s of STATUSES) counts[s] = 0;
  const byKey = new Map();
  const groups = cat.groups.map((g) => ({ ...g, count: 0, allObscure: true }));
  const groupAt = new Map(groups.map((g) => [g.id, g]));
  for (const r of rows) {
    counts[r.status] += 1;
    counts.withheld += r.withheld;
    if (r.discovered) counts.discovered += 1;
    if (r.problem) counts.problems += 1;
    byKey.set(r.key, r);
    const g = groupAt.get(r.group);
    if (g) {
      g.count += 1;
      if (r.priority !== 'obscure') g.allObscure = false;
    }
  }
  const alertInputs = {};
  for (const a of cat.alerts) {
    if (!isObj(a) || !isStr(a.entity_id) || hasOwn(alertInputs, a.entity_id)) continue;
    const s = st[a.entity_id];
    alertInputs[a.entity_id] = isObj(s)
      ? { present: true, state: s.state === null || s.state === undefined ? 'unknown' : String(s.state), attributes: isObj(s.attributes) ? s.attributes : {} }
      : { present: false, state: null, attributes: {} };
  }
  return { schema: 'ecco-geek-snapshot/1', viewId: cat.viewId, title: cat.title, contract: cat.contract, nowMs, rows, byKey, groups, counts, alertInputs, exceptions: cat.exceptions };
}

/** Every ledger id the card can show for a catalogue: each source id and each declared attribute path (source id # path). */
export function catalogueItemIds(catalogue) {
  const out = [];
  for (const s of prepare(catalogue).sources) {
    out.push(s.id);
    for (const a of s.attributes || []) out.push(`${s.id}#${a.name}`);
  }
  return out;
}

// ===========================================================================
// 5. alerts and the Production summary
// ===========================================================================
const SEVERITY_WORDS = Object.freeze({ critical: 'Critical', warning: 'Warning', info: 'Notice' });

function evaluate(when, input) {
  const down = !input.present || input.state === 'unavailable' || input.state === 'unknown';
  if (when.unavailable === true) return down ? 'active' : 'clear';
  if (when.state_not_in) return down || !when.state_not_in.includes(input.state) ? 'active' : 'clear';
  if (down) return 'unknown';
  if (when.state_in) return when.state_in.includes(input.state) ? 'active' : 'clear';
  if (when.attribute) {
    const v = input.attributes[when.attribute];
    if (v === undefined || v === null) return 'unknown';
    return when.in.includes(String(v)) ? 'active' : 'clear';
  }
  return 'unknown';
}

/**
 * The alerts that are active right now, critical first. A condition that cannot be evaluated because its entity is unavailable,
 * unknown, missing or lacks the attribute is reported as an "unverifiable" alert (at most a warning), so the strip is never
 * silently clear: unless an `unavailable` alert on the same entity is already active and says it.
 */
export function deriveAlerts(snapshot, catalogue) {
  const inputs = snapshot && isObj(snapshot.alertInputs) ? snapshot.alertInputs : {};
  const list = (isObj(catalogue) && Array.isArray(catalogue.alerts) ? catalogue.alerts : []).filter((a) => isObj(a) && validWhen(a.when) && SEVERITIES.includes(a.severity)
    && isStr(a.id) && isStr(a.entity_id));
  const out = [];
  const downActive = new Set();
  const verdict = list.map((a) => {
    const input = hasOwn(inputs, a.entity_id) ? inputs[a.entity_id] : { present: false, state: null, attributes: {} };
    const v = evaluate(a.when, input);
    if (v === 'active' && a.when.unavailable === true) downActive.add(a.entity_id);
    return v;
  });
  list.forEach((a, i) => {
    if (verdict[i] === 'active') out.push({ id: a.id, severity: a.severity, entity_id: a.entity_id, text: a.text, action: a.action, kind: 'condition', order: i });
    else if (verdict[i] === 'unknown' && !downActive.has(a.entity_id)) {
      out.push({ id: `${a.id}:unverifiable`, severity: a.severity === 'info' ? 'info' : 'warning', entity_id: a.entity_id, text: `Cannot check this right now: ${a.text}`,
        action: 'Wait for the data to return. If it does not, check the source in Geek Mode.', kind: 'unverifiable', order: 1000 + i });
    }
  });
  return out.sort((x, y) => SEVERITY_RANK[x.severity] - SEVERITY_RANK[y.severity] || x.order - y.order);
}

/** One calm sentence for Production Mode, from the same snapshot and alert list. */
export function summarise(snapshot, alerts) {
  const list = Array.isArray(alerts) ? alerts : [];
  const by = (s) => list.filter((a) => a.severity === s);
  const more = (arr) => (arr.length > 1 ? ` (and ${arr.length - 1} more)` : '');
  let level = 'ok';
  let text = 'Everything this view watches looks normal.';
  if (by('critical').length) {
    level = 'critical';
    text = `${by('critical')[0].text}${more(by('critical'))}`;
  } else if (by('warning').length) {
    level = 'attention';
    text = `${by('warning')[0].text}${more(by('warning'))}`;
  } else if (by('info').length) {
    level = 'info';
    text = `${by('info')[0].text}${more(by('info'))}`;
  }
  const n = snapshot && snapshot.counts ? snapshot.counts.problems : 0;
  return { level, text, note: n ? `${n} data point${n === 1 ? ' is' : 's are'} stale, unavailable, simulated or unverified. Geek Mode lists them.` : '' };
}

// ===========================================================================
// 6. search, windowing, export
// ===========================================================================
/** Filter and search rows. Every term (space separated, case-insensitive) must appear in the row's search text. */
export function searchRows(rows, query = '', filters = {}) {
  const terms = String(query).toLowerCase().split(/\s+/).filter(Boolean).slice(0, 8);
  const f = isObj(filters) ? filters : {};
  const want = (v) => v !== undefined && v !== null && v !== '' && v !== 'all';
  return (Array.isArray(rows) ? rows : []).filter((r) => (!want(f.status) || r.status === f.status || r.flags.includes(f.status))
    && (!want(f.group) || r.group === f.group) && (!want(f.priority) || r.priority === f.priority) && (!f.problems || r.problem)
    && terms.every((t) => r.searchText.includes(t)));
}

/** One page of a list: { rows, page (clamped), pageCount, total, start (inclusive), end (exclusive) }. */
export function windowRows(rows, page, pageSize) {
  const list = Array.isArray(rows) ? rows : [];
  const size = Math.min(Math.max(Number.isFinite(pageSize) ? Math.floor(pageSize) : LIMITS.pageSize, 1), LIMITS.maxPageSize);
  const pageCount = Math.max(1, Math.ceil(list.length / size));
  const p = Math.min(Math.max(Number.isFinite(page) ? Math.floor(page) : 0, 0), pageCount - 1);
  const start = p * size;
  const end = Math.min(start + size, list.length);
  return { rows: list.slice(start, end), page: p, pageCount, total: list.length, start, end };
}

function exportState(r) {
  if (r.status === 'NOT_MEASURED' || r.present === false) return null;
  if (r.status === 'UNAVAILABLE') return 'unavailable';
  if (r.status === 'UNKNOWN') return 'unknown';
  return r.stateText;
}

function exportRow(r) {
  return {
    id: r.id, entity_id: r.entity_id, group: r.group, title: r.title, priority: r.priority, status: r.status, flags: r.flags, state: exportState(r),
    unit: r.unitText ? r.unitText : null, age_s: isNum(r.ageS) ? Math.round(r.ageS) : null, last_updated: isNum(r.lastUpdated) ? new Date(r.lastUpdated).toISOString() : null,
    source: r.origin, discovered: !!r.discovered, attributes: r.redacted || {}, absent_attributes: (r.attributes || []).filter((a) => a.declared && !a.present).map((a) => a.path),
  };
}

const csvCell = (v) => {
  let s = v === null || v === undefined ? '' : String(v);
  if (/^[=+\-@\t\r]/.test(s)) s = `'${s}`;
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
};

/**
 * The non-secret diagnostics of some rows as json or csv text. Built only from the redacted, displayed data, then passed
 * through the redactor once more (defence in depth: even a hand-made row cannot carry a secret out). CSV cells that start
 * with = + - @ are neutralised against spreadsheet formula injection.
 */
export function exportRows(rows, format = 'json', meta = {}) {
  if (format !== 'json' && format !== 'csv') throw new Error('unsupported export format');
  const m = isObj(meta) ? meta : {};
  const items = redactValue((Array.isArray(rows) ? rows : []).map(exportRow));
  if (format === 'json') {
    const doc = { schema: EXPORT_SCHEMA, view_id: isStr(m.viewId) ? cleanText(m.viewId, 80) : '', generated_at: isNum(m.nowMs) ? new Date(m.nowMs).toISOString() : null,
      count: items.length, note: 'Values that look secret or private are replaced by the word withheld. Nothing here can change ECCO.', rows: items };
    return JSON.stringify(doc, null, 2);
  }
  const head = ['id', 'entity_id', 'group', 'title', 'status', 'state', 'unit', 'age_s', 'attributes'];
  const lines = [head.join(',')];
  for (const it of items) lines.push([it.id, it.entity_id, it.group, it.title, it.status, it.state, it.unit, it.age_s, JSON.stringify(it.attributes)].map(csvCell).join(','));
  return `${lines.join('\n')}\n`;
}

// ===========================================================================
// 7. the child-card guard
// ===========================================================================
const SAFE_ACTIONS = Object.freeze(['none', 'more-info', 'navigate']);
const WRITE_CARD_TYPES = new Set(['button', 'entity-button', 'light', 'thermostat', 'humidifier', 'media-control', 'alarm-panel', 'shopping-list', 'todo-list',
  'iframe', 'webpage']);
const WRITABLE_DOMAINS = new Set(['switch', 'light', 'input_boolean', 'fan', 'cover', 'lock', 'climate', 'automation', 'script', 'scene', 'button', 'input_button',
  'select', 'input_select', 'number', 'input_number', 'input_datetime', 'input_text', 'text', 'humidifier', 'valve', 'vacuum', 'water_heater', 'media_player',
  'siren', 'update', 'remote', 'alarm_control_panel', 'lawn_mower', 'datetime', 'date', 'time']);
const READ_ONLY_ROW_TYPES = new Set(['simple-entity', 'attribute', 'divider', 'section', 'text', 'conditional']);
const CALL_KEYS = new Set(['service', 'service_data', 'perform_action', 'call-service']);

/**
 * Child cards shown in a Geek-visible region (the `always` list) must not be able to write: refuse any action other than
 * none, more-info or navigate, any service-call shaped key, write-capable card types, entities-card rows of a writable
 * domain and tile cards on a writable domain that do not state safe actions. Returns { ok, errors: [{index, path, action?,
 * message}], allowed: [index...] }. Never throws.
 */
export function validateChildCards(cards) {
  const errors = [];
  const allowed = [];
  if (cards !== undefined && !Array.isArray(cards)) return { ok: false, errors: [{ index: -1, path: 'cards', message: 'the card list must be a list' }], allowed };
  (cards || []).forEach((card, index) => {
    const before = errors.length;
    const bad = (path, message, action) => errors.push(action === undefined ? { index, path, message } : { index, path, action, message });
    if (!isObj(card)) bad('card', 'a card configuration must be an object');
    else if (!isStr(card.type) || card.type === '') bad('type', 'a card configuration needs a type');
    else walkCard(card, 'card', bad, new Set(), 0);
    if (errors.length === before) allowed.push(index);
  });
  return { ok: errors.length === 0, errors, allowed };
}

function walkCard(node, path, bad, seen, depth) {
  if (depth > 12 || seen.has(node)) return;
  seen.add(node);
  if (Array.isArray(node)) {
    node.forEach((x, i) => {
      if (x !== null && typeof x === 'object') walkCard(x, `${path}[${i}]`, bad, seen, depth + 1);
    });
    return;
  }
  const type = isStr(node.type) ? node.type : '';
  if (WRITE_CARD_TYPES.has(type)) bad(`${path}.type`, `a ${type} card can write, so it is not allowed here`);
  if (type === 'tile' && isStr(node.entity) && WRITABLE_DOMAINS.has(node.entity.split('.')[0])) {
    for (const k of ['tap_action', 'icon_tap_action']) if (!isObj(node[k])) bad(`${path}.${k}`, `a tile on ${node.entity.split('.')[0]} must state a safe ${k}`);
  }
  if (type === 'tile' && Array.isArray(node.features) && node.features.length) bad(`${path}.features`, 'tile features can write');
  if (isObj(node) && 'action' in node && !(isStr(node.action) && SAFE_ACTIONS.includes(node.action))) {
    bad(`${path}.action`, `the action ${isStr(node.action) ? node.action : '(not text)'} is not allowed here (only none, more-info or navigate)`, isStr(node.action) ? node.action : '');
  }
  for (const k of Object.keys(node)) {
    const v = node[k];
    if (CALL_KEYS.has(k)) bad(`${path}.${k}`, `${k} would call a service, so it is not allowed here`);
    if (k !== 'action' && (k.endsWith('_action') || k === 'actions')) {
      const inner = Array.isArray(v) ? v : [v];
      for (const x of inner) if (!isObj(x)) bad(`${path}.${k}`, `${k} must be an action object`);
    }
    if (k === 'entities' && type === 'entities' && Array.isArray(v)) {
      v.forEach((row, i) => {
        const where = `${path}.entities[${i}]`;
        const eid = isStr(row) ? row : isObj(row) && isStr(row.entity) ? row.entity : '';
        const rtype = isObj(row) && isStr(row.type) ? row.type : '';
        if (rtype !== '' && !READ_ONLY_ROW_TYPES.has(rtype)) bad(where, `a ${rtype} row can write or open a link, so it is not allowed here`);
        if (rtype === '' && eid !== '' && WRITABLE_DOMAINS.has(eid.split('.')[0])) bad(where, `a row on ${eid.split('.')[0]} shows a control, so it is not allowed here`);
      });
    }
    if (v !== null && typeof v === 'object') walkCard(v, `${path}.${k}`, bad, seen, depth + 1);
  }
}

// ===========================================================================
// 8. palette and style
// ===========================================================================
// Three surfaces, each checked against WCAG AA by the node tests: the light and dark Home Assistant card surfaces (status
// colours are used for icons and borders; every status is ALSO said in words), and the dark instrument panel that Geek Mode
// uses in both themes.
export const PALETTE = Object.freeze({
  light: Object.freeze({ surface: '#ffffff', fg: '#1b2330', fg2: '#4a5565', accent: '#3b45c4', live: '#13693b', stale: '#8a4b00', unavailable: '#a8201a',
    unknown: '#515c6b', simulated: '#5b32a8', unverified: '#7a4d00' }),
  dark: Object.freeze({ surface: '#172133', fg: '#e8edf4', fg2: '#aab5c4', accent: '#9db4ff', live: '#6fdca0', stale: '#f2bd5c', unavailable: '#ff9d94',
    unknown: '#b4bfce', simulated: '#c9b0ff', unverified: '#f2bd5c' }),
  panel: Object.freeze({ surface: '#0f1a2e', fg: '#e9f0fb', fg2: '#b7c4d8', accent: '#7fe3ff', live: '#6fdca0', stale: '#f2bd5c', unavailable: '#ff9d94',
    unknown: '#b4bfce', simulated: '#c9b0ff', unverified: '#f2bd5c' }),
});
/** The two stops of the switch thumb's gradient; white text on each is checked by the tests. */
export const THUMB = Object.freeze(['#3b45c4', '#6a3fd0']);

const palVars = (p) => `--ecco-live:${p.live};--ecco-stale:${p.stale};--ecco-unavailable:${p.unavailable};--ecco-unknown:${p.unknown};`
  + `--ecco-simulated:${p.simulated};--ecco-unverified:${p.unverified};--ecco-accent:${p.accent};`;
const themeVars = (p) => `${palVars(p)}--ecco-surface:var(--card-background-color,${p.surface});--ecco-fg:var(--primary-text-color,${p.fg});`
  + `--ecco-fg2:var(--secondary-text-color,${p.fg2});--ecco-line:var(--divider-color,${p === PALETTE.dark ? 'rgba(255,255,255,.18)' : 'rgba(80,90,110,.32)'});`;
const STATUS_VAR = Object.freeze({ LIVE: 'live', STALE: 'stale', UNAVAILABLE: 'unavailable', UNKNOWN: 'unknown', NOT_MEASURED: 'unknown', SIMULATED: 'simulated', UNVERIFIED: 'unverified' });
const statusRules = STATUSES.map((s) => `[data-status="${s}"],[data-status-chip="${s}"],[data-count-status="${s}"],[data-seg="${s}"]{--ecco-st:var(--ecco-${STATUS_VAR[s]})}`).join('\n');

export const STYLE = `
:host{display:block;container-type:inline-size;min-width:0}
*,*::before,*::after{box-sizing:border-box}
[hidden]{display:none!important}
.shell{${themeVars(PALETTE.light)}--ecco-chip:rgba(128,128,150,.14);--ecco-track:rgba(128,128,150,.18);--ecco-focus:var(--ecco-accent);
display:grid;gap:12px;min-width:0;max-width:100%;color:var(--ecco-fg);font:14px/1.45 var(--paper-font-body1_-_font-family,"Segoe UI",Roboto,Arial,sans-serif);overflow-wrap:anywhere}
.shell[data-theme="dark"]{${themeVars(PALETTE.dark)}}
@media (prefers-color-scheme: dark){.shell:not([data-theme="light"]){${themeVars(PALETTE.dark)}}}
${statusRules}
.top{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:10px 16px;min-width:0}
.title{margin:0;font-size:1.15rem;font-weight:700;letter-spacing:.2px;min-width:0}
.mode-note{margin:-6px 0 0;color:var(--ecco-fg2);font-size:.8rem}
.switch{position:relative;display:inline-grid;grid-template-columns:1fr 1fr;padding:4px;border-radius:999px;background:var(--ecco-track);border:1px solid var(--ecco-line);box-shadow:inset 0 1px 3px rgba(0,0,0,.18)}
.thumb{position:absolute;top:4px;bottom:4px;left:4px;width:calc(50% - 4px);border-radius:999px;background:linear-gradient(135deg,${THUMB[0]},${THUMB[1]});box-shadow:0 4px 14px rgba(70,60,200,.45),inset 0 1px 0 rgba(255,255,255,.35);transition:transform .32s cubic-bezier(.2,.9,.25,1.1)}
.switch[data-mode="geek"] .thumb{transform:translateX(100%)}
.opt{position:relative;z-index:1;display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:44px;min-width:44px;padding:0 16px;border:0;border-radius:999px;background:transparent;color:var(--ecco-fg2);font:inherit;font-weight:650;cursor:pointer;transition:color .2s}
.opt[aria-checked="true"]{color:#fff}
.ico{width:18px;height:18px;flex:none;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
:focus-visible{outline:3px solid var(--ecco-focus);outline-offset:2px}
.alerts{display:grid;gap:8px;min-width:0}
.alert{display:grid;grid-template-columns:auto minmax(0,1fr);gap:2px 10px;align-items:start;padding:10px 12px;border:1px solid var(--ecco-line);border-left:6px solid var(--ecco-accent);border-radius:12px;background:var(--ecco-surface)}
.alert>.ico{width:22px;height:22px;grid-row:1/3;color:var(--ecco-accent)}
.alert[data-severity="critical"]{border-left-color:var(--ecco-unavailable)}
.alert[data-severity="critical"]>.ico{color:var(--ecco-unavailable)}
.alert[data-severity="warning"]{border-left-color:var(--ecco-stale)}
.alert[data-severity="warning"]>.ico{color:var(--ecco-stale)}
.alert.quiet{border-left-color:var(--ecco-live);align-items:center}
.alert.quiet>.ico{grid-row:auto;color:var(--ecco-live)}
.alert-head{font-weight:700}
.alert-action{margin:0;color:var(--ecco-fg2);font-size:.9rem;grid-column:2}
.summary{margin:0;padding:12px 14px;border-radius:14px;background:var(--ecco-surface);border:1px solid var(--ecco-line);font-size:1.02rem}
.summary small{display:block;margin-top:4px;color:var(--ecco-fg2);font-size:.82rem}
.child{min-width:0}
.notice{padding:10px 12px;border-radius:12px;border:1px solid var(--ecco-line);border-left:6px solid var(--ecco-stale);background:var(--ecco-surface)}
.region{display:grid;gap:12px;min-width:0}
.panel{${palVars(PALETTE.panel)}--ecco-fg:${PALETTE.panel.fg};--ecco-fg2:${PALETTE.panel.fg2};--ecco-line:rgba(160,190,255,.22);--ecco-focus:#7fe3ff;
position:relative;display:grid;gap:12px;min-width:0;padding:14px;border-radius:18px;color:var(--ecco-fg);overflow:hidden;
background:radial-gradient(120% 80% at 0% 0%,rgba(127,227,255,.14),transparent 60%),radial-gradient(90% 70% at 100% 0%,rgba(150,110,255,.18),transparent 55%),linear-gradient(165deg,#13203a,${PALETTE.panel.surface});
border:1px solid rgba(160,190,255,.2);box-shadow:0 10px 30px rgba(6,10,24,.35),inset 0 1px 0 rgba(255,255,255,.08)}
.panel-head{display:grid;gap:2px}
.panel-title{margin:0;font-size:1rem;letter-spacing:.14em;text-transform:uppercase;color:var(--ecco-accent)}
.panel-sub{margin:0;color:var(--ecco-fg2);font-size:.82rem}
.counts{display:grid;grid-template-columns:repeat(auto-fit,minmax(122px,1fr));gap:8px}
.count{display:grid;grid-template-columns:auto minmax(0,1fr);align-items:center;gap:0 8px;padding:8px 10px;border-radius:12px;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.14)}
.count>.ico{grid-row:1/3;width:22px;height:22px;color:var(--ecco-st,var(--ecco-fg2))}
.count strong{font:700 1.3rem/1.1 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.count span{font-size:.78rem;color:var(--ecco-fg2);overflow-wrap:normal}
.healthbar{display:flex;height:10px;border-radius:999px;overflow:hidden;background:rgba(255,255,255,.1)}
.healthbar>span{flex:var(--ecco-w,1) 1 0;min-width:4px;background:var(--ecco-st)}
.healthbar>[data-seg="STALE"]{background:repeating-linear-gradient(45deg,var(--ecco-st) 0 4px,transparent 4px 8px)}
.healthbar>[data-seg="UNKNOWN"],.healthbar>[data-seg="NOT_MEASURED"]{background:radial-gradient(circle,var(--ecco-st) 0 1.6px,transparent 2px) 0 0/6px 10px}
.healthbar>[data-seg="UNAVAILABLE"]{background:repeating-linear-gradient(90deg,var(--ecco-st) 0 3px,transparent 3px 5px)}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(184px,1fr));gap:10px}
.tile{position:relative;min-width:0;border-radius:14px;background:linear-gradient(160deg,rgba(255,255,255,.1),rgba(255,255,255,.03));border:1px solid rgba(255,255,255,.16)}
.tile-btn{display:grid;grid-template-columns:auto minmax(0,1fr);gap:10px;align-items:center;width:100%;min-height:44px;padding:10px;border:0;border-radius:14px;background:transparent;color:inherit;font:inherit;text-align:left;cursor:pointer}
.ring{position:relative;display:grid;place-items:center;width:48px;height:48px;border-radius:50%;background:conic-gradient(var(--ecco-st) calc(var(--ecco-p,0)*1%),rgba(255,255,255,.16) 0)}
.ring::after{content:"";position:absolute;inset:5px;border-radius:50%;background:${PALETTE.panel.surface}}
.ring>.ico{position:relative;z-index:1;width:22px;height:22px;color:var(--ecco-st)}
.tile[data-ring="empty"] .ring{background:repeating-conic-gradient(rgba(255,255,255,.3) 0 8deg,transparent 8deg 24deg)}
.tile[data-ring="none"] .ring{background:conic-gradient(rgba(255,255,255,.24) 0 100%)}
.tile-body{display:grid;gap:1px;min-width:0}
.tile-name{font-size:.78rem;color:var(--ecco-fg2);overflow-wrap:break-word}
.tile-val{font:700 1rem/1.2 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;min-width:0;overflow-wrap:break-word}
.tile-sub{font-size:.76rem;overflow-wrap:break-word}
@media (prefers-reduced-motion: no-preference){.tile[data-status="LIVE"] .ring{animation:ecco-pulse 3.2s ease-in-out infinite}}
@keyframes ecco-pulse{0%,100%{box-shadow:0 0 0 0 rgba(111,220,160,0)}50%{box-shadow:0 0 14px 2px rgba(111,220,160,.38)}}
.inspector{display:grid;gap:10px;min-width:0;padding:12px;border-radius:16px;background:var(--ecco-surface);border:1px solid var(--ecco-line)}
.toolbar{display:grid;gap:8px;min-width:0}
.fields{display:grid;gap:8px;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));min-width:0}
.actions{display:flex;flex-wrap:wrap;gap:8px}
.search{position:relative;display:block;min-width:0}
.search>.ico{position:absolute;left:12px;top:13px;width:18px;height:18px;color:var(--ecco-fg2);pointer-events:none}
.field{min-height:44px;width:100%;min-width:0;padding:0 12px;border-radius:12px;border:1px solid var(--ecco-line);background:var(--ecco-surface);color:var(--ecco-fg);font:inherit}
.search .field{padding-left:38px}
.btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:44px;min-width:44px;padding:0 14px;border-radius:12px;border:1px solid var(--ecco-line);background:var(--ecco-surface);color:var(--ecco-fg);font:inherit;font-weight:600;cursor:pointer}
.btn[aria-pressed="true"],.btn[aria-expanded="true"]{border-color:var(--ecco-accent);box-shadow:inset 0 0 0 1px var(--ecco-accent)}
.btn:disabled,.btn[disabled]{opacity:.55;cursor:not-allowed}
.status-line{min-height:1.2em;margin:0;color:var(--ecco-fg2);font-size:.82rem}
.groupbar{display:flex;flex-wrap:wrap;gap:8px}
.gbtn .ico{transition:transform .2s}
.gbtn[aria-expanded="false"] .ico{transform:rotate(-90deg)}
.list{display:grid;gap:8px;min-width:0}
.grouplabel{margin:8px 0 0;font-size:.76rem;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--ecco-fg2)}
.row{min-width:0;overflow:hidden;border:1px solid var(--ecco-line);border-radius:14px;background:var(--ecco-surface)}
.row-toggle{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:4px 10px;align-items:center;width:100%;min-height:44px;padding:10px 12px;border:0;background:transparent;color:inherit;font:inherit;text-align:left;cursor:pointer}
.row-main{display:grid;gap:1px;min-width:0}
.row-title{font-weight:650}
.row-ids{color:var(--ecco-fg2);font:.74rem ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.row-side{display:grid;gap:1px;justify-items:end;min-width:0;text-align:right}
.row-state{font:600 .95rem ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.row-age{color:var(--ecco-fg2);font-size:.76rem}
.chips{display:flex;flex-wrap:wrap;gap:6px;align-items:center}
.chip{display:inline-flex;align-items:center;gap:6px;padding:3px 10px;border-radius:999px;border:1.5px solid var(--ecco-st,var(--ecco-line));background:var(--ecco-chip);color:var(--ecco-fg);font-size:.78rem;font-weight:650;white-space:nowrap;text-overflow:ellipsis}
.chip>.ico{width:16px;height:16px;color:var(--ecco-st)}
[data-status-chip="STALE"]{border-style:dashed}
[data-status-chip="UNKNOWN"],[data-status-chip="NOT_MEASURED"]{border-style:dotted}
[data-status-chip="UNAVAILABLE"]{border-style:double;border-width:3px}
.tag{padding:1px 8px;border-radius:8px;border:1px solid var(--ecco-line);color:var(--ecco-fg2);font-size:.72rem}
.withheld{display:inline-flex;align-items:center;gap:6px;padding:1px 8px;border-radius:8px;border:1px dashed var(--ecco-fg2);color:var(--ecco-fg2);font-style:italic}
.withheld>.ico{width:14px;height:14px}
.detail{display:grid;gap:10px;min-width:0;padding:8px 12px 12px;border-top:1px dashed var(--ecco-line)}
.detail p{margin:0}
.meta{display:flex;flex-wrap:wrap;gap:4px 14px;color:var(--ecco-fg2);font-size:.8rem}
.attrs{display:grid;gap:6px;min-width:0}
.attr{display:grid;grid-template-columns:minmax(0,1fr);gap:2px;min-width:0;padding:6px 8px;border-radius:10px;background:var(--ecco-chip)}
.attr[data-depth="1"],.attr[data-depth="2"]{margin-left:12px;border-left:3px solid var(--ecco-line)}
.attr[data-attr-state="absent"]{background:transparent;border:1px dashed var(--ecco-line)}
.attr-name{font:600 .82rem ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.attr-val{min-width:0;font:.84rem ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.attr-desc{min-width:0;color:var(--ecco-fg2);font-size:.82rem}
.rowacts{display:flex;flex-wrap:wrap;gap:8px}
.raw{margin:0;max-height:320px;overflow:auto;padding:10px;border-radius:10px;border:1px solid var(--ecco-line);background:var(--ecco-chip);font:.78rem/1.45 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:pre-wrap;overflow-wrap:anywhere}
.empty{padding:14px;border-radius:12px;border:1px dashed var(--ecco-line);text-align:center}
.pager{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:8px}
.pager-info{color:var(--ecco-fg2);font-size:.85rem}
.keys{display:grid;gap:6px;margin:0;padding:0;list-style:none}
.keys li{display:flex;gap:8px;align-items:flex-start;flex-wrap:wrap}
.fine{margin:0;color:var(--ecco-fg2);font-size:.82rem}
@container (min-width:561px){.attr{grid-template-columns:minmax(120px,.9fr) minmax(0,1.2fr) minmax(0,1.6fr);align-items:start}.toolbar{grid-template-columns:minmax(180px,1.1fr) minmax(0,2.6fr) auto;align-items:start}}
@container (max-width:560px){.row-toggle{grid-template-columns:minmax(0,1fr)}.row-side{justify-items:start;text-align:left}.counts{grid-template-columns:repeat(2,minmax(0,1fr))}.tiles{grid-template-columns:repeat(2,minmax(0,1fr))}.tile-btn{gap:8px;padding:8px}.ring{width:40px;height:40px}.ring::after{inset:4px}.ring>.ico{width:20px;height:20px}.tile-val{font-size:.88rem}.opt{padding:0 12px}.top{align-items:stretch}.switch{width:100%}}
@media (prefers-reduced-motion: reduce){*,*::before,*::after{animation: none !important;transition: none !important;scroll-behavior:auto !important}}
`;

// ===========================================================================
// 9. DOM builders and icons
// ===========================================================================
// An SVG namespace identifier, not a network resource (assembled so that this file holds no URL at all).
const SVG_NS = ['http:', '', 'www.w3.org', '2000', 'svg'].join('/');
const C9 = { cx: 12, cy: 12, r: 9 };
const ICON_SHAPES = Object.freeze({
  live: [['circle', C9], ['path', { d: 'M8 12.5l2.7 2.7L16 9.5' }]],
  stale: [['circle', C9], ['path', { d: 'M12 7v5.2l3 1.8' }]],
  unavailable: [['circle', C9], ['path', { d: 'M6 6l12 12' }]],
  unknown: [['circle', C9], ['path', { d: 'M9.6 9.4a2.6 2.6 0 1 1 3.7 2.3c-.8.4-1.3 1-1.3 1.9' }], ['path', { d: 'M12 17.2h.01' }]],
  not_measured: [['circle', { cx: 12, cy: 12, r: 9, 'stroke-dasharray': '3 3' }], ['path', { d: 'M8.5 12h7' }]],
  simulated: [['path', { d: 'M9.5 3h5M10.5 3v6.2L5.6 17.4a2 2 0 0 0 1.7 3.1h9.4a2 2 0 0 0 1.7-3.1L13.5 9.2V3' }], ['path', { d: 'M8.5 15h7' }]],
  unverified: [['path', { d: 'M12 3l7 3v5.2c0 4.4-2.9 7.9-7 9.8-4.1-1.9-7-5.4-7-9.8V6z' }], ['path', { d: 'M12 8.5v3.8' }], ['path', { d: 'M12 15.6h.01' }]],
  withheld: [['path', { d: 'M3 3l18 18' }], ['path', { d: 'M10.6 6.1A9.6 9.6 0 0 1 12 6c5 0 8.5 4 9.5 6a14 14 0 0 1-2.3 3.1M6.5 7A14 14 0 0 0 2.5 12c1 2 4.5 6 9.5 6 1.4 0 2.6-.3 3.7-.8' }]],
  critical: [['path', { d: 'M12 3.5l9.5 16.5h-19z' }], ['path', { d: 'M12 10v4.5' }], ['path', { d: 'M12 17.6h.01' }]],
  warning: [['circle', C9], ['path', { d: 'M12 7.5v5' }], ['path', { d: 'M12 16h.01' }]],
  info: [['circle', C9], ['path', { d: 'M12 11v5' }], ['path', { d: 'M12 7.8h.01' }]],
  production: [['path', { d: 'M4 11.5L12 4l8 7.5' }], ['path', { d: 'M6.5 10v9.5h11V10' }], ['path', { d: 'M10 19.5v-5h4v5' }]],
  geek: [['path', { d: 'M8 7l-5 5 5 5' }], ['path', { d: 'M16 7l5 5-5 5' }], ['path', { d: 'M13.5 5l-3 14' }]],
  search: [['circle', { cx: 11, cy: 11, r: 6.5 }], ['path', { d: 'M20 20l-4.2-4.2' }]],
  copy: [['rect', { x: 9, y: 9, width: 11, height: 11, rx: 2 }], ['path', { d: 'M5 15V6a2 2 0 0 1 2-2h8' }]],
  download: [['path', { d: 'M12 4v11' }], ['path', { d: 'M7.5 11L12 15.5 16.5 11' }], ['path', { d: 'M5 19.5h14' }]],
  chevron: [['path', { d: 'M7 10l5 5 5-5' }]],
  open: [['path', { d: 'M14 4h6v6' }], ['path', { d: 'M20 4l-9 9' }], ['path', { d: 'M18 14v5.5H4.5V6H10' }]],
  raw: [['path', { d: 'M8 5c-2 0-3 1-3 3v2c0 1.2-.6 2-2 2 1.4 0 2 .8 2 2v2c0 2 1 3 3 3' }], ['path', { d: 'M16 5c2 0 3 1 3 3v2c0 1.2.6 2 2 2-1.4 0-2 .8-2 2v2c0 2-1 3-3 3' }]],
  problems: [['path', { d: 'M12 3.5l9.5 16.5h-19z' }], ['path', { d: 'M12 10v4.5' }]],
});
const STATUS_ICON = Object.freeze({ LIVE: 'live', STALE: 'stale', UNAVAILABLE: 'unavailable', UNKNOWN: 'unknown', NOT_MEASURED: 'not_measured', SIMULATED: 'simulated', UNVERIFIED: 'unverified' });
const STATUS_WORD = Object.freeze({ LIVE: 'Live', STALE: 'Stale', UNAVAILABLE: 'Unavailable', UNKNOWN: 'Unknown', NOT_MEASURED: 'Not measured', SIMULATED: 'Simulated', UNVERIFIED: 'Unverified' });
const STATUS_HELP = Object.freeze({
  LIVE: 'A value is reporting and, if the source has a freshness limit, it is within it. Some sources have no limit: their age is shown but not monitored.',
  STALE: 'The value is older than its freshness limit. It is shown for reference only and is not current.',
  UNAVAILABLE: 'Home Assistant reports the source as unavailable. No value is shown.',
  UNKNOWN: 'The source has no value yet. No value is shown.',
  NOT_MEASURED: 'The catalogue lists this data point but Home Assistant has no such entity. Nothing is invented.',
  SIMULATED: 'The source marks this value as simulated, not measured.',
  UNVERIFIED: 'The source says the value is not verified, or it has a freshness limit but no usable timestamp.',
});

/** Build an element. `tag` and the attribute NAMES are always literals in this file; only attribute VALUES and text may come from data. */
function mk(doc, tag, attrs, kids) {
  const el = doc.createElement(tag);
  if (attrs) {
    for (const k of Object.keys(attrs)) {
      const v = attrs[k];
      if (v === undefined || v === null || v === false) continue;
      el.setAttribute(k, v === true ? '' : String(v));
    }
  }
  if (kids !== undefined) put(el, kids);
  return el;
}

function put(el, kids) {
  for (const k of Array.isArray(kids) ? kids : [kids]) {
    if (k === null || k === undefined || k === false) continue;
    el.appendChild(typeof k === 'object' ? k : el.ownerDocument.createTextNode(String(k)));
  }
}

function icon(doc, name) {
  const shapes = ICON_SHAPES[name] || ICON_SHAPES.unknown;
  const svg = doc.createElementNS(SVG_NS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('class', 'ico');
  for (const [shapeTag, attrs] of shapes) {
    const n = doc.createElementNS(SVG_NS, shapeTag);
    for (const k of Object.keys(attrs)) n.setAttribute(k, String(attrs[k]));
    svg.appendChild(n);
  }
  return svg;
}

/** A value, or the withheld marker (an icon and the word, never colour alone). */
function valueNode(doc, text) {
  if (text === WITHHELD) return mk(doc, 'span', { class: 'withheld', 'data-withheld': '', title: 'This value looks secret or private, so it is not shown.' }, [icon(doc, 'withheld'), 'Withheld']);
  return doc.createTextNode(text);
}

const chipNode = (doc, status) => mk(doc, 'span', { class: 'chip', 'data-status-chip': status }, [icon(doc, STATUS_ICON[status]), mk(doc, 'span', null, STATUS_WORD[status])]);

function alertNode(doc, a) {
  const critical = a.severity === 'critical';
  const el = mk(doc, 'div', { class: 'alert', 'data-alert-id': a.id, 'data-severity': a.severity, 'data-alert-kind': a.kind, 'data-entity-id': a.entity_id || null, role: critical ? 'alert' : 'status' });
  put(el, [icon(doc, a.severity), mk(doc, 'div', { class: 'alert-head' }, [`${SEVERITY_WORDS[a.severity]}: `, a.text]), mk(doc, 'p', { class: 'alert-action' }, `What to do: ${a.action}`)]);
  return el;
}

/** THE alert strip renderer: both modes use this one function and this one element, which sits outside both switchable bodies. */
function renderAlertStrip(doc, strip, alerts) {
  strip.setAttribute('data-alert-count', String(alerts.length));
  const kids = alerts.length ? alerts.map((a) => alertNode(doc, a)) : [mk(doc, 'div', { class: 'alert quiet', 'data-alert-none': '' }, [icon(doc, 'live'), mk(doc, 'span', null, 'No active alerts.')])];
  strip.replaceChildren(...kids);
}

/** A raw view of one row: the redacted attributes as pretty text, capped. */
function rawText(row) {
  const body = { entity_id: row.entity_id, state: exportState(row), unit: row.unitText || null, status: row.status, attributes: row.redacted || {} };
  const t = JSON.stringify(body, null, 2);
  return t.length > LIMITS.rawChars ? `${t.slice(0, LIMITS.rawChars)}\n\u2026 [truncated ${t.length - LIMITS.rawChars} more characters]` : t;
}

function attrNode(doc, a) {
  const state = !a.present ? 'absent' : a.kind === 'null' ? 'null' : 'present';
  const desc = `${a.description || 'Not described by the catalogue.'}${a.unit ? ` Unit: ${a.unit}.` : ''}`;
  return mk(doc, 'div', { class: 'attr', 'data-attribute-path': a.path, 'data-attr-state': state, 'data-depth': a.depth, 'data-declared': a.declared ? 'true' : 'false' }, [
    mk(doc, 'span', { class: 'attr-name' }, a.depth ? `\u21b3 ${a.name}` : a.name),
    mk(doc, 'span', { class: 'attr-val' }, [a.withheld ? valueNode(doc, WITHHELD) : doc.createTextNode(a.value)]),
    mk(doc, 'span', { class: 'attr-desc' }, desc),
  ]);
}

function ringOf(r) {
  if (r.status === 'STALE') return { mode: 'empty', pct: null };
  if (r.ageMonitored && isNum(r.ageS) && isNum(r.stale_after_s) && r.stale_after_s > 0 && r.present && r.status !== 'UNAVAILABLE' && r.status !== 'UNKNOWN') {
    return { mode: 'percent', pct: Math.max(0, Math.min(100, Math.round(100 * (1 - r.ageS / r.stale_after_s)))) };
  }
  return { mode: 'none', pct: null };
}

// ===========================================================================
// 10. the Geek surface
// ===========================================================================
const DEFAULT_FILTERS = Object.freeze({ status: 'all', group: 'all', priority: 'all', problems: false });
const on = (el, type, fn) => el.addEventListener(type, fn);

/**
 * Everything that exists only in Geek Mode: the instrument panel (counts, health bar, headline tiles), the searchable,
 * filterable, grouped, paged inventory with per-row attribute lists and a redacted raw view, copy and export, the catalogue's
 * exceptions and the status key. It is built when Geek Mode is entered and dropped when it is left; it holds no state outside
 * this instance. It reads only the snapshot it is given and calls back into the element for the three things it may do:
 * open an entity (an event), copy text and download text.
 */
class GeekSurface {
  constructor(opts) {
    this.o = opts;
    this.doc = opts.doc;
    this.q = '';
    this.filters = { ...DEFAULT_FILTERS };
    this.page = 0;
    this.collapsed = new Map();
    this.open = new Set();
    this.raw = new Set();
    this.cache = new Map();
    this.stats = { rowBuilds: 0, listRenders: 0, fullRebuilds: 0 };
    this.snap = null;
    this.ui = {};
    this.groupSig = '';
  }

  build() {
    const { doc } = this;
    const host = this.o.container;
    host.replaceChildren();
    if (!this.o.catalogueOk) {
      host.appendChild(this._errorPanel());
      host.appendChild(this._controlsNote());
      return;
    }
    const ui = this.ui;
    ui.counts = mk(doc, 'div', { class: 'counts', 'data-ecco-counts': '' });
    ui.bar = mk(doc, 'div', { class: 'healthbar', 'data-ecco-healthbar': '', role: 'img', 'aria-label': 'Share of data points by status' });
    ui.tiles = mk(doc, 'div', { class: 'tiles', 'data-ecco-tiles': '' });
    ui.sub = mk(doc, 'p', { class: 'panel-sub', 'data-geek-sub': '' });
    const panel = mk(doc, 'section', { class: 'panel', 'data-ecco-panel': '', 'aria-label': 'Geek Mode instrument panel' }, [
      mk(doc, 'div', { class: 'panel-head' }, [mk(doc, 'h3', { class: 'panel-title' }, 'Geek Mode'), ui.sub]), ui.counts, ui.bar, ui.tiles,
    ]);
    host.appendChild(panel);
    host.appendChild(this._buildInspector());
    host.appendChild(this._buildExceptions());
    host.appendChild(this._buildKey());
    host.appendChild(this._controlsNote());
  }

  _errorPanel() {
    const { doc } = this;
    const errs = (this.o.errors || []).slice(0, 12);
    return mk(doc, 'section', { class: 'notice', 'data-ecco-catalogue-error': '', role: 'alert' }, [
      mk(doc, 'strong', null, 'Geek Mode is switched off: the catalogue is not valid.'),
      mk(doc, 'p', { class: 'fine' }, 'Nothing is shown rather than something that might be incomplete. The alert strip above still works from the alerts that are valid.'),
      ...errs.map((e) => mk(doc, 'p', { class: 'fine', 'data-catalogue-problem': '' }, [mk(doc, 'code', null, e.path), `: ${e.message}`])),
    ]);
  }

  _controlsNote() {
    const { doc } = this;
    const back = mk(doc, 'button', { type: 'button', class: 'btn', 'data-geek-to-production': '' }, [icon(doc, 'production'), 'Back to Production view']);
    on(back, 'click', () => this.o.onLeave());
    return mk(doc, 'p', { class: 'fine', 'data-geek-controls-note': '' }, ['Geek Mode only shows. Controls (such as the pause switch) live in the Production view, unchanged. ', back]);
  }

  _buildInspector() {
    const { doc } = this;
    const ui = this.ui;
    ui.search = mk(doc, 'input', { type: 'search', class: 'field', 'data-inspector-search': '', 'aria-label': 'Search data points: name, entity, value or attribute', placeholder: 'Search every data point', autocomplete: 'off', spellcheck: 'false' });
    on(ui.search, 'input', () => {
      this.q = ui.search.value;
      this.page = 0;
      this._renderList();
    });
    const select = (name, label, options) => {
      const s = mk(doc, 'select', { class: 'field', 'data-inspector-filter': name, 'aria-label': label });
      for (const [value, text] of options) s.appendChild(mk(doc, 'option', { value }, text));
      s.value = 'all';
      on(s, 'change', () => {
        this.filters[name] = s.value;
        this.page = 0;
        this._renderList();
      });
      return s;
    };
    ui.status = select('status', 'Filter by status', [['all', 'Any status'], ...STATUSES.map((s) => [s, STATUS_WORD[s]])]);
    ui.group = select('group', 'Filter by group', [['all', 'Any group']]);
    ui.priority = select('priority', 'Filter by importance', [['all', 'Any importance'], ['headline', 'Headline'], ['normal', 'Normal'], ['obscure', 'Obscure']]);
    ui.problems = mk(doc, 'button', { type: 'button', class: 'btn', 'data-inspector-filter': 'problems', 'aria-pressed': 'false', title: 'Show only data points that are not live' }, [icon(doc, 'problems'), 'Problems only']);
    on(ui.problems, 'click', () => {
      this.filters.problems = !this.filters.problems;
      this.page = 0;
      this._renderList();
    });
    const copy = mk(doc, 'button', { type: 'button', class: 'btn', 'data-inspector-copy': 'all', title: 'Copy the matching data points as non-secret JSON' }, [icon(doc, 'copy'), 'Copy']);
    on(copy, 'click', () => this.o.onCopy(this._exportText('json'), 'the matching data points'));
    const json = mk(doc, 'button', { type: 'button', class: 'btn', 'data-inspector-export': 'json', title: 'Download the matching data points as non-secret JSON' }, [icon(doc, 'download'), 'JSON']);
    on(json, 'click', () => this.o.onDownload('json', this._exportText('json')));
    const csv = mk(doc, 'button', { type: 'button', class: 'btn', 'data-inspector-export': 'csv', title: 'Download the matching data points as non-secret CSV' }, [icon(doc, 'download'), 'CSV']);
    on(csv, 'click', () => this.o.onDownload('csv', this._exportText('csv')));
    ui.status_line = mk(doc, 'p', { class: 'status-line', 'data-inspector-status': '', 'aria-live': 'polite' });
    ui.groupbar = mk(doc, 'div', { class: 'groupbar', 'data-group-bar': '' });
    ui.list = mk(doc, 'div', { class: 'list', 'data-inspector-list': '', role: 'list', 'aria-label': 'Data points' });
    const clear = mk(doc, 'button', { type: 'button', class: 'btn', 'data-inspector-clear': '' }, 'Clear search and filters');
    on(clear, 'click', () => this._clear());
    ui.empty = mk(doc, 'div', { class: 'empty', 'data-inspector-empty': '' }, [mk(doc, 'p', null, 'No data points match your search or filters.'), clear]);
    ui.prev = mk(doc, 'button', { type: 'button', class: 'btn', 'data-inspector-page-prev': '', 'aria-label': 'Previous page' }, 'Previous');
    ui.next = mk(doc, 'button', { type: 'button', class: 'btn', 'data-inspector-page-next': '', 'aria-label': 'Next page' }, 'Next');
    on(ui.prev, 'click', () => {
      if (this.page > 0) {
        this.page -= 1;
        this._renderList();
      }
    });
    on(ui.next, 'click', () => {
      this.page += 1;
      this._renderList();
    });
    ui.info = mk(doc, 'span', { class: 'pager-info', 'data-inspector-page-info': '' });
    ui.hiddenNote = mk(doc, 'span', { class: 'pager-info', 'data-inspector-hidden-note': '' });
    return mk(doc, 'section', { class: 'inspector', 'data-ecco-inspector': '', 'aria-label': 'Data point inventory' }, [
      mk(doc, 'div', { class: 'toolbar' }, [
        mk(doc, 'label', { class: 'search' }, [icon(doc, 'search'), ui.search]),
        mk(doc, 'div', { class: 'fields' }, [ui.status, ui.group, ui.priority, ui.problems]),
        mk(doc, 'div', { class: 'actions' }, [copy, json, csv]),
      ]),
      ui.status_line, ui.groupbar, ui.list, ui.empty,
      mk(doc, 'div', { class: 'pager' }, [ui.prev, mk(doc, 'span', null, [ui.info, ' ', ui.hiddenNote]), ui.next]),
    ]);
  }

  _buildExceptions() {
    const { doc } = this;
    const list = this.o.exceptions || [];
    const items = list.map((x) => mk(doc, 'li', { 'data-exception': x.id, 'data-reason': x.reason }, [mk(doc, 'span', { class: 'tag' }, x.reason.replace(/_/g, ' ')), mk(doc, 'strong', null, x.what), x.note ? mk(doc, 'span', { class: 'fine' }, x.note) : null]));
    return mk(doc, 'section', { class: 'inspector', 'data-exceptions': '', 'aria-label': 'Not shown, and why' }, [
      mk(doc, 'h3', { class: 'grouplabel' }, 'Not shown in Geek Mode, and why'),
      items.length ? mk(doc, 'ul', { class: 'keys' }, items) : mk(doc, 'p', { class: 'fine' }, 'The catalogue lists no exceptions.'),
    ]);
  }

  _buildKey() {
    const { doc } = this;
    return mk(doc, 'section', { class: 'inspector', 'data-status-key': '', 'aria-label': 'What the status words mean' }, [
      mk(doc, 'h3', { class: 'grouplabel' }, 'What the status words mean'),
      mk(doc, 'ul', { class: 'keys' }, STATUSES.map((s) => mk(doc, 'li', null, [chipNode(doc, s), mk(doc, 'span', { class: 'fine' }, STATUS_HELP[s])]))),
    ]);
  }

  /** Give the surface a new snapshot (called on every data change and clock tick). */
  update(snap) {
    this.snap = snap;
    if (!this.o.catalogueOk) return;
    this._renderHeader();
    this._renderTiles();
    this._syncGroups();
    this._renderList();
  }

  say(text) {
    if (this.ui.status_line) this.ui.status_line.textContent = text;
  }

  _renderHeader() {
    const { doc } = this;
    const snap = this.snap;
    const c = snap.counts;
    const shown = STATUSES.filter((s) => c[s] > 0 || ['LIVE', 'STALE', 'UNAVAILABLE', 'NOT_MEASURED'].includes(s));
    const tiles = shown.map((s) => mk(doc, 'div', { class: 'count', 'data-count-status': s, 'data-count': c[s] }, [icon(doc, STATUS_ICON[s]), mk(doc, 'strong', null, String(c[s])), mk(doc, 'span', null, STATUS_WORD[s])]));
    tiles.push(mk(doc, 'div', { class: 'count', 'data-count-withheld': '', 'data-count': c.withheld, title: 'Values held back because they look secret or private' }, [icon(doc, 'withheld'), mk(doc, 'strong', null, String(c.withheld)), mk(doc, 'span', null, 'Withheld')]));
    this.ui.counts.replaceChildren(...tiles);
    const segs = STATUSES.filter((s) => c[s] > 0).map((s) => {
      const seg = mk(doc, 'span', { 'data-seg': s, title: `${STATUS_WORD[s]}: ${c[s]}` });
      seg.style.setProperty('--ecco-w', String(c[s]));
      return seg;
    });
    this.ui.bar.replaceChildren(...segs);
    this.ui.sub.textContent = `${this.o.fmtTime(snap.nowMs)} \u00b7 ${c.total} data points${c.discovered ? ` (${c.discovered} discovered)` : ''}${snap.contract ? ` \u00b7 ${snap.contract}` : ''}`;
  }

  _renderTiles() {
    const { doc } = this;
    const heads = this.snap.rows.filter((r) => !r.discovered && r.priority === 'headline').slice(0, LIMITS.tiles);
    this.ui.tiles.hidden = heads.length === 0;
    this.ui.tiles.replaceChildren(...heads.map((r) => {
      const ring = ringOf(r);
      const el = mk(doc, 'div', { class: 'tile', 'data-tile': '', 'data-entity-id': r.entity_id, 'data-status': r.status, 'data-ring': ring.mode, 'data-ring-percent': ring.pct });
      const ringEl = mk(doc, 'span', { class: 'ring', 'aria-hidden': 'true' }, [icon(doc, STATUS_ICON[r.status])]);
      if (ring.mode === 'percent') ringEl.style.setProperty('--ecco-p', String(ring.pct));
      const val = mk(doc, 'span', { class: 'tile-val' }, [r.stateText === WITHHELD ? valueNode(doc, WITHHELD) : doc.createTextNode(r.unitText ? `${r.stateText} ${r.unitText}` : r.stateText)]);
      const btn = mk(doc, 'button', { type: 'button', class: 'tile-btn', 'data-tile-focus': '', 'aria-label': `Show details for ${r.title}` }, [
        ringEl, mk(doc, 'span', { class: 'tile-body' }, [mk(doc, 'span', { class: 'tile-name' }, r.title), val, mk(doc, 'span', { class: 'tile-sub' }, `${STATUS_WORD[r.status]} \u00b7 ${r.ageText}`)]),
      ]);
      on(btn, 'click', () => this._focusRow(r));
      el.appendChild(btn);
      return el;
    }));
  }

  _focusRow(r) {
    this.q = r.entity_id;
    this.filters = { ...DEFAULT_FILTERS };
    this.page = 0;
    this.collapsed.set(r.group, false);
    this.open.add(r.key);
    this._syncControls();
    this._renderList();
  }

  _syncControls() {
    const ui = this.ui;
    ui.search.value = this.q;
    ui.status.value = this.filters.status;
    ui.group.value = this.filters.group;
    ui.priority.value = this.filters.priority;
  }

  _clear() {
    this.q = '';
    this.filters = { ...DEFAULT_FILTERS };
    this.page = 0;
    this._syncControls();
    this._renderList();
  }

  /** Keep the group filter's options in step with the snapshot's groups. */
  _syncGroups() {
    const { doc } = this;
    const ids = this.snap.groups.filter((g) => g.count > 0).map((g) => `${g.id}\u0001${g.title}`).join('\u0002');
    if (ids === this.groupSig) return;
    this.groupSig = ids;
    if (this.filters.group !== 'all' && !this.snap.groups.some((g) => g.id === this.filters.group && g.count > 0)) this.filters.group = 'all';
    const s = this.ui.group;
    s.replaceChildren(mk(doc, 'option', { value: 'all' }, 'Any group'), ...this.snap.groups.filter((g) => g.count > 0).map((g) => mk(doc, 'option', { value: g.id }, g.title)));
    s.value = this.filters.group;
  }

  _isOpen(g) {
    if (this.collapsed.has(g.id)) return !this.collapsed.get(g.id);
    return !(g.allObscure && g.count > 0 && g.id !== 'discovered');
  }

  _matching() {
    return searchRows(this.snap.rows, this.q, this.filters);
  }

  _exportText(format) {
    return exportRows(this._matching(), format, { viewId: this.snap.viewId, nowMs: this.snap.nowMs });
  }

  _renderList() {
    const { doc } = this;
    const snap = this.snap;
    const ui = this.ui;
    const focusKey = this.o.activeKey();
    const filtered = this._matching();
    const by = new Map();
    for (const r of filtered) {
      let a = by.get(r.group);
      if (!a) {
        a = [];
        by.set(r.group, a);
      }
      a.push(r);
    }
    const visible = [];
    const bar = [];
    let collapsedRows = 0;
    for (const g of snap.groups) {
      const rs = by.get(g.id);
      if (!rs) continue;
      const open = this._isOpen(g);
      bar.push({ g, count: rs.length, open });
      if (open) for (const r of rs) visible.push(r);
      else collapsedRows += rs.length;
    }
    const win = windowRows(visible, this.page, this.o.pageSize);
    this.page = win.page;
    // the group bar: one toggle per group that has matches
    ui.groupbar.replaceChildren(...bar.map(({ g, count, open }) => {
      const b = mk(doc, 'button', { type: 'button', class: 'btn gbtn', 'data-group-toggle': g.id, 'aria-expanded': open ? 'true' : 'false', 'data-focus-key': `g:${g.id}` }, [icon(doc, 'chevron'), `${g.title} (${count})`]);
      on(b, 'click', () => {
        const cur = this.snap.groups.find((x) => x.id === g.id) || g;
        this.collapsed.set(g.id, this._isOpen(cur));
        this.page = 0;
        this._renderList();
      });
      return b;
    }));
    // the rows of this page: unchanged rows keep their node; only a changed row is rebuilt
    const kids = [];
    const used = new Set();
    let built = 0;
    let last = null;
    const titleOf = new Map(snap.groups.map((g) => [g.id, g.title]));
    for (const row of win.rows) {
      if (row.group !== last) {
        kids.push(mk(doc, 'h3', { class: 'grouplabel' }, titleOf.get(row.group) || row.group));
        last = row.group;
      }
      const open = this.open.has(row.key);
      const raw = this.raw.has(row.key);
      const sig = `${row.sig}\u0002${open ? 1 : 0}${raw ? 1 : 0}`;
      used.add(row.key);
      const hit = this.cache.get(row.key);
      if (hit && hit.sig === sig) {
        kids.push(hit.el);
        continue;
      }
      this.stats.rowBuilds += 1;
      built += 1;
      const el = this._buildRow(row, open, raw);
      this.cache.set(row.key, { sig, el });
      kids.push(el);
    }
    for (const k of [...this.cache.keys()]) if (!used.has(k)) this.cache.delete(k);
    ui.list.replaceChildren(...kids);
    this.stats.listRenders += 1;
    if (built === win.rows.length && built > 1) this.stats.fullRebuilds += 1;
    // chrome around the list
    ui.empty.hidden = filtered.length !== 0;
    ui.problems.setAttribute('aria-pressed', this.filters.problems ? 'true' : 'false');
    ui.prev.toggleAttribute('disabled', win.page <= 0);
    ui.next.toggleAttribute('disabled', win.page >= win.pageCount - 1);
    ui.info.textContent = win.total ? `${win.start + 1}\u2013${win.end} of ${win.total}` : '0\u20130 of 0';
    ui.hiddenNote.textContent = collapsedRows ? `(${collapsedRows} more in collapsed groups)` : '';
    if (focusKey) {
      for (const n of ui.groupbar.querySelectorAll('[data-focus-key]')) if (n.getAttribute('data-focus-key') === focusKey) n.focus();
      for (const n of ui.list.querySelectorAll('[data-focus-key]')) if (n.getAttribute('data-focus-key') === focusKey) n.focus();
    }
  }

  _buildRow(row, open, raw) {
    const { doc } = this;
    const key = row.key;
    const el = mk(doc, 'div', {
      class: 'row', role: 'listitem', 'data-inspector-row': '', 'data-entity-id': row.entity_id, 'data-status': row.status, 'data-group': row.group,
      'data-priority': row.priority, 'data-source-id': row.id, 'data-discovered': row.discovered ? 'true' : 'false',
    });
    const extra = row.flags.slice(1).map((f) => mk(doc, 'span', { class: 'tag', 'data-flag-chip': f }, STATUS_WORD[f]));
    const idText = row.discovered ? (row.title === row.entity_id ? 'discovered' : `${row.entity_id} \u00b7 discovered`) : `${row.id} \u00b7 ${row.entity_id}`;
    const idLine = mk(doc, 'span', { class: 'row-ids' }, idText);
    const stateNode = mk(doc, 'span', { class: 'row-state', 'data-row-state': '' }, [row.stateText === WITHHELD ? valueNode(doc, WITHHELD) : doc.createTextNode(row.unitText ? `${row.stateText} ${row.unitText}` : row.stateText)]);
    const ageWords = row.status === 'NOT_MEASURED' ? 'no data' : `${row.ageText}${row.ageMonitored ? '' : ' \u00b7 age not monitored'}`;
    const toggle = mk(doc, 'button', { type: 'button', class: 'row-toggle', 'data-row-toggle': '', 'data-row-head': '', 'aria-expanded': open ? 'true' : 'false', 'data-focus-key': `${key}:t` }, [
      mk(doc, 'span', { class: 'chips' }, [chipNode(doc, row.status), ...extra]),
      mk(doc, 'span', { class: 'row-main' }, [mk(doc, 'span', { class: 'row-title' }, row.title), idLine]),
      mk(doc, 'span', { class: 'row-side' }, [stateNode, mk(doc, 'span', { class: 'row-age', 'data-row-age': '' }, ageWords)]),
    ]);
    on(toggle, 'click', () => {
      if (this.open.has(key)) this.open.delete(key);
      else this.open.add(key);
      this._renderList();
    });
    el.appendChild(toggle);
    if (!open) return el;
    const attrs = mk(doc, 'div', { class: 'attrs', role: 'list', 'aria-label': 'Attributes' });
    for (const a of row.attributes) attrs.appendChild(attrNode(doc, a));
    const acts = [];
    if (row.present && row.entity_id !== WITHHELD) {
      const openBtn = mk(doc, 'button', { type: 'button', class: 'btn', 'data-open-entity': '', 'data-focus-key': `${key}:o` }, [icon(doc, 'open'), 'Open in Home Assistant']);
      on(openBtn, 'click', () => this.o.onOpen(row.entity_id));
      acts.push(openBtn);
    }
    if (row.present) {
      const rawBtn = mk(doc, 'button', { type: 'button', class: 'btn', 'data-raw-toggle': '', 'aria-pressed': raw ? 'true' : 'false', 'data-focus-key': `${key}:r` }, [icon(doc, 'raw'), raw ? 'Hide raw attributes' : 'Raw attributes']);
      on(rawBtn, 'click', () => {
        if (this.raw.has(key)) this.raw.delete(key);
        else this.raw.add(key);
        this._renderList();
      });
      acts.push(rawBtn);
    }
    const copyBtn = mk(doc, 'button', { type: 'button', class: 'btn', 'data-inspector-copy': 'row', 'data-focus-key': `${key}:c` }, [icon(doc, 'copy'), 'Copy']);
    on(copyBtn, 'click', () => {
      const r = this.snap.byKey.get(key);
      if (r) this.o.onCopy(exportRows([r], 'json', { viewId: this.snap.viewId, nowMs: this.snap.nowMs }), 'this data point');
    });
    acts.push(copyBtn);
    const meta = [`Group: ${(this.snap.groups.find((g) => g.id === row.group) || { title: row.group }).title}`, `Source: ${row.origin}`, `Importance: ${row.priority}`,
      row.lastUpdated === null ? 'Last updated: unknown' : `Last updated: ${this.o.fmtTime(row.lastUpdated)}`,
      row.stale_after_s === null ? 'Freshness limit: none' : `Freshness limit: ${row.stale_after_s} s`,
      row.expected_update_s === null ? null : `Expected every: ${row.expected_update_s} s`,
      `Attributes: ${row.attrTotal}`].filter(Boolean);
    const detail = mk(doc, 'div', { class: 'detail', 'data-row-detail': '' }, [
      mk(doc, 'p', null, row.description || 'No description in the catalogue.'),
      mk(doc, 'div', { class: 'meta' }, meta.map((m) => mk(doc, 'span', null, m))),
      attrs,
      mk(doc, 'div', { class: 'rowacts' }, acts),
    ]);
    if (raw && row.present) detail.appendChild(mk(doc, 'pre', { class: 'raw', 'data-inspector-raw': '', tabindex: '0', 'aria-label': 'Raw attributes (redacted)' }, rawText(row)));
    el.appendChild(detail);
    return el;
  }
}

// ===========================================================================
// 11. the custom element
// ===========================================================================
const Base = typeof HTMLElement !== 'undefined' ? HTMLElement : class {};

export class EccoModeShell extends Base {
  constructor() {
    super();
    this._config = null;
    this._cat = null;
    this._shellAlerts = [];
    this._hass = null;
    this._now = () => Date.now();
    this._ctl = createModeController({ onChange: () => this._applyMode() });
    this._root = typeof this.attachShadow === 'function' ? this.attachShadow({ mode: 'open' }) : null;
    this._ui = null;
    this._geek = null;
    this._snap = null;
    this._alerts = [];
    this._kids = [];
    this._gen = 0;
    this._timer = null;
    this._entryPath = '';
    this._ro = null;
    this._connected = false;
    this._lastStates = null;
    this._lastNow = 0;
    this._onLocation = () => {
      if (this._pathNow() !== this._entryPath) this._ctl.reset();
    };
    this._onPageHide = () => this._ctl.reset();
  }

  static getStubConfig() {
    return { type: `custom:${TAG}`, view_id: 'example', title: 'Example view', always: [], production: [] };
  }

  /** The presentation mode, read-only: it can only be changed by the switch in this element's own shadow DOM. */
  get mode() {
    return this._ctl.mode;
  }

  get snapshot() {
    return this._snap;
  }

  get alerts() {
    return this._alerts;
  }

  get inspectorStats() {
    return this._geek ? { ...this._geek.stats } : { rowBuilds: 0, listRenders: 0, fullRebuilds: 0 };
  }

  setConfig(config) {
    const cfg = validateConfig(config);
    this._config = cfg;
    this._cat = validateCatalogue(cfg.catalogue);
    this._shellAlerts = [];
    if (!this._cat.ok) {
      this._shellAlerts.push({ id: 'shell:catalogue-invalid', severity: 'warning', entity_id: '', kind: 'shell', text: 'The Geek Mode catalogue is not valid, so the Geek Mode inventory is switched off.',
        action: 'Ask whoever installed this view to fix the catalogue. Everything else on this view still works.' });
    }
    this._build();
    this._lastStates = null;
    this._refresh(true);
  }

  getCardSize() {
    return 6;
  }

  getGridOptions() {
    return { columns: 'full', rows: 'auto', min_columns: 6 };
  }

  get hass() {
    return this._hass;
  }

  set hass(hass) {
    this._hass = hass;
    for (const k of this._kids) k.hass = hass;
    this._refresh(false);
  }

  connectedCallback() {
    // Explicit reset on entry: Home Assistant may keep a component alive, and every entry starts in Production.
    this._ctl.reset();
    this._resetUi();
    this._unlisten();
    this._connected = true;
    this._entryPath = this._pathNow();
    if (typeof window !== 'undefined' && typeof window.addEventListener === 'function') {
      window.addEventListener('location-changed', this._onLocation);
      window.addEventListener('pagehide', this._onPageHide);
    }
    if (typeof ResizeObserver !== 'undefined') {
      this._ro = new ResizeObserver((entries) => {
        for (const e of entries) {
          const r = e.contentRect;
          if (r && r.width === 0 && r.height === 0) this._ctl.reset();
        }
      });
      this._ro.observe(this);
    }
    if (this._timer === null) this._timer = setInterval(() => this._tick(), TICK_MS);
    this._refresh(true);
  }

  disconnectedCallback() {
    this._unlisten();
    this._connected = false;
    this._ctl.reset();
  }

  _unlisten() {
    if (typeof window !== 'undefined' && typeof window.removeEventListener === 'function') {
      window.removeEventListener('location-changed', this._onLocation);
      window.removeEventListener('pagehide', this._onPageHide);
    }
    if (this._ro) this._ro.disconnect();
    this._ro = null;
    if (this._timer !== null) clearInterval(this._timer);
    this._timer = null;
  }

  _pathNow() {
    return typeof window !== 'undefined' && window.location && isStr(window.location.pathname) ? window.location.pathname : '';
  }

  _resetUi() {
    this._disposeGeek();
  }

  _disposeGeek() {
    this._geek = null;
    if (this._ui) this._ui.geekBody.replaceChildren();
  }

  _tick() {
    this._refresh(true);
  }

  _statesObj() {
    const hass = this._hass;
    const s = hass && hass.states;
    return isObj(s) ? s : {};
  }

  _fmtTime(ms) {
    const hass = this._hass;
    const lang = hass && hass.locale && isStr(hass.locale.language) ? hass.locale.language : undefined;
    try {
      return new Intl.DateTimeFormat(lang, { dateStyle: 'short', timeStyle: 'medium' }).format(new Date(ms));
    } catch {
      return new Date(ms).toISOString();
    }
  }

  // ---- building the static structure ----
  _build() {
    if (!this._root) return;
    const doc = this.ownerDocument;
    this._gen += 1;
    this._kids = [];
    this._geek = null;
    const cfg = this._config;
    const style = mk(doc, 'style');
    style.textContent = STYLE;
    const opts = {};
    const optNode = (mode, label, hint) => {
      const b = mk(doc, 'button', { type: 'button', role: 'radio', class: 'opt', 'data-mode-option': mode, 'aria-checked': 'false', tabindex: '-1', 'aria-label': hint, title: hint }, [icon(doc, mode), mk(doc, 'span', null, label)]);
      on(b, 'click', () => this._ctl.set(mode));
      opts[mode] = b;
      return b;
    };
    const sw = mk(doc, 'div', { class: 'switch', role: 'radiogroup', 'aria-label': 'View mode', 'data-ecco-mode-switch': '', 'data-mode': this._ctl.mode }, [
      mk(doc, 'span', { class: 'thumb', 'aria-hidden': 'true' }), optNode('production', 'Production', 'Production view: calm and simple'), optNode('geek', 'Geek', 'Geek view: every available data point'),
    ]);
    on(sw, 'keydown', (ev) => this._onSwitchKey(ev));
    const title = cfg.title || (this._cat && this._cat.catalogue.title) || 'View';
    const strip = mk(doc, 'div', { class: 'alerts', 'data-ecco-alert-strip': '', role: 'region', 'aria-label': 'Safety and status alerts', 'aria-live': 'polite' });
    const always = mk(doc, 'div', { class: 'region', 'data-ecco-always': '' });
    const summary = mk(doc, 'p', { class: 'summary', 'data-ecco-summary': '', 'data-level': 'ok' });
    const prodKids = mk(doc, 'div', { class: 'region', 'data-ecco-production-children': '' });
    const prodBody = mk(doc, 'div', { class: 'region', 'data-ecco-body': 'production' }, [summary, prodKids]);
    const geekBody = mk(doc, 'div', { class: 'region', 'data-ecco-body': 'geek' });
    const shell = mk(doc, 'div', { class: 'shell', 'data-ecco-shell': '', 'data-view': cfg.viewId || (this._cat && this._cat.catalogue.view_id) || null, 'data-mode': this._ctl.mode }, [
      mk(doc, 'div', { class: 'top' }, [mk(doc, 'h2', { class: 'title' }, title), sw]),
      mk(doc, 'p', { class: 'mode-note', 'data-ecco-mode-note': '' }, 'This switch only changes what is shown. It never changes what ECCO does.'),
      strip, always, prodBody, geekBody,
    ]);
    this._root.replaceChildren(style, shell);
    this._ui = { shell, sw, opts, strip, always, summary, prodKids, prodBody, geekBody };
    const refused = this._mountChildren(always, cfg.always, true);
    this._mountChildren(prodKids, cfg.production, false);
    if (refused.length) {
      this._shellAlerts.push({ id: 'shell:child-refused', severity: 'warning', entity_id: '', kind: 'shell', text: 'A card was not shown because it could change something, and this region may only show.',
        action: 'Move that card to the production list, or remove its action.' });
    }
    this._applyMode();
  }

  _mountChildren(container, configs, guard) {
    const refused = [];
    const verdict = guard ? validateChildCards(configs) : { allowed: configs.map((_, i) => i), errors: [] };
    const allowed = new Set(verdict.allowed);
    configs.forEach((cfg, i) => {
      if (!allowed.has(i)) {
        const why = verdict.errors.filter((e) => e.index === i).map((e) => e.message).join(' ');
        refused.push(i);
        container.appendChild(this._notice('data-child-refused', `Card not shown: ${why}`));
        return;
      }
      this._mountChild(container, cfg);
    });
    return refused;
  }

  _notice(flag, text) {
    const doc = this.ownerDocument;
    return mk(doc, 'div', { class: 'notice', [flag]: '', role: 'note' }, cleanText(text, 400));
  }

  _mountChild(container, cfg) {
    const doc = this.ownerDocument;
    const wrap = mk(doc, 'div', { class: 'child', 'data-child': '' });
    container.appendChild(wrap);
    const gen = this._gen;
    const fail = (message) => {
      if (gen === this._gen) wrap.appendChild(this._notice('data-child-error', `Card could not be shown: ${message}`));
    };
    if (!isObj(cfg) || !isStr(cfg.type) || cfg.type === '') {
      fail('its configuration needs a type.');
      return;
    }
    const attach = (el) => {
      if (gen !== this._gen) return;
      wrap.appendChild(el);
      this._kids.push(el);
      if (this._hass !== null && this._hass !== undefined) el.hass = this._hass;
    };
    const helpers = typeof window !== 'undefined' && typeof window.loadCardHelpers === 'function' ? window.loadCardHelpers : null;
    if (helpers) {
      helpers().then((hp) => attach(hp.createCardElement(cfg))).catch((e) => fail(e && e.message ? e.message : 'unknown error'));
      return;
    }
    if (cfg.type.startsWith('custom:')) {
      const cfgTag = cfg.type.slice(7);
      if (!/^[a-z][a-z0-9]*(-[a-z0-9]+)+$/.test(cfgTag)) {
        fail('the card type is not a valid element name.');
        return;
      }
      const el = doc.createElement(cfgTag);
      if (typeof el.setConfig !== 'function') {
        fail(`${cfgTag} is not available. Is its resource loaded?`);
        return;
      }
      try {
        el.setConfig(cfg);
      } catch (e) {
        fail(e && e.message ? e.message : 'its configuration was refused.');
        return;
      }
      attach(el);
      return;
    }
    fail('this card type needs Home Assistant card helpers, which are not available here.');
  }

  // ---- the mode ----
  _onSwitchKey(ev) {
    const order = MODES;
    const i = order.indexOf(this._ctl.mode);
    let next = null;
    if (ev.key === 'ArrowRight' || ev.key === 'ArrowDown') next = order[(i + 1) % order.length];
    else if (ev.key === 'ArrowLeft' || ev.key === 'ArrowUp') next = order[(i + order.length - 1) % order.length];
    else if (ev.key === 'Home') next = order[0];
    else if (ev.key === 'End') next = order[order.length - 1];
    if (next === null) return;
    if (typeof ev.preventDefault === 'function') ev.preventDefault();
    this._ctl.set(next);
    if (this._ui) this._ui.opts[next].focus();
  }

  _applyMode() {
    const ui = this._ui;
    if (!ui) return;
    const mode = this._ctl.mode;
    ui.shell.setAttribute('data-mode', mode);
    ui.sw.setAttribute('data-mode', mode);
    for (const m of MODES) {
      ui.opts[m].setAttribute('aria-checked', m === mode ? 'true' : 'false');
      ui.opts[m].setAttribute('tabindex', m === mode ? '0' : '-1');
    }
    ui.prodBody.hidden = mode !== 'production';
    ui.geekBody.hidden = mode !== 'geek';
    if (mode === 'geek') {
      if (!this._geek) {
        this._geek = new GeekSurface({
          doc: this.ownerDocument, container: ui.geekBody, catalogueOk: this._cat.ok, errors: this._cat.errors, exceptions: this._cat.catalogue.exceptions,
          pageSize: this._config.pageSize, fmtTime: (ms) => this._fmtTime(ms), onOpen: (eid) => this._openEntity(eid), onCopy: (text, what) => this._copy(text, what),
          onDownload: (fmt, text) => this._download(fmt, text), onLeave: () => this._ctl.set('production'), activeKey: () => this._activeKey(),
        });
        this._geek.build();
      }
      if (this._snap) this._geek.update(this._snap);
    } else this._disposeGeek();
  }

  _activeKey() {
    const a = this._root && this._root.activeElement;
    return a && typeof a.getAttribute === 'function' ? a.getAttribute('data-focus-key') : null;
  }

  // ---- data flow: one snapshot feeds everything ----
  _refresh(force) {
    const ui = this._ui;
    if (!ui) return;
    const states = this._statesObj();
    const now = this._now();
    if (!force && states === this._lastStates && now - this._lastNow < 1000) return;
    this._lastStates = states;
    this._lastNow = now;
    const cat = this._cat.catalogue;
    const effective = this._cat.ok ? cat : { ...cat, sources: [], discover: { entity_prefixes: [], group: 'discovered', exclude_entity_ids: [] } };
    this._snap = buildSnapshot(states, effective, now);
    this._alerts = [...deriveAlerts(this._snap, cat), ...this._shellAlerts];
    const hass = this._hass;
    if (hass && hass.themes && typeof hass.themes.darkMode === 'boolean') ui.shell.setAttribute('data-theme', hass.themes.darkMode ? 'dark' : 'light');
    else ui.shell.removeAttribute('data-theme');
    renderAlertStrip(this.ownerDocument, ui.strip, this._alerts);
    const sum = summarise(this._snap, this._alerts);
    ui.summary.setAttribute('data-level', sum.level);
    ui.summary.replaceChildren(this.ownerDocument.createTextNode(sum.text), ...(sum.note ? [mk(this.ownerDocument, 'small', null, sum.note)] : []));
    if (this._geek) this._geek.update(this._snap);
  }

  // ---- the only three things the shell may do besides read ----
  _openEntity(entityId) {
    if (typeof CustomEvent !== 'function') return;
    this.dispatchEvent(new CustomEvent('hass-more-info', { bubbles: true, composed: true, detail: { entityId } }));
  }

  _copy(text, what) {
    const clip = typeof navigator !== 'undefined' && navigator.clipboard && typeof navigator.clipboard.writeText === 'function' ? navigator.clipboard : null;
    const say = (m) => {
      if (this._geek) this._geek.say(m);
    };
    if (!clip) {
      say('Copy is not available in this browser context. Use the JSON or CSV button instead.');
      return;
    }
    clip.writeText(text).then(() => say(`Copied ${what} (non-secret values only).`), () => say('The browser blocked the copy. Use the JSON or CSV button instead.'));
  }

  _download(format, text) {
    const doc = this.ownerDocument;
    const snap = this._snap;
    const stamp = new Date(snap ? snap.nowMs : this._now()).toISOString().slice(0, 19).replace(/[-:]/g, '').replace('T', '-');
    const view = String(snap && snap.viewId ? snap.viewId : 'view').toLowerCase().replace(/[^a-z0-9-]+/g, '-').slice(0, 40) || 'view';
    const blob = new Blob([text], { type: format === 'csv' ? 'text/csv;charset=utf-8' : 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = doc.createElement('a');
    a.setAttribute('href', url);
    a.setAttribute('download', `ecco-${view}-diagnostics-${stamp}.${format}`);
    this._root.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    if (this._geek) this._geek.say(`Downloaded ${format.toUpperCase()} (non-secret values only).`);
  }
}

// ---------------------------------------------------------------------------
// the mode controller: the ONLY holder of the mode, one per element instance
// ---------------------------------------------------------------------------
/**
 * A mode controller. The mode is only ever 'production' or 'geek'; a new controller is 'production'; reset() returns to
 * 'production'. onChange(mode, 'set' | 'reset') is called only when the mode actually changes. It holds no reference to hass
 * and has no way to do anything but remember a presentation choice.
 */
export function createModeController({ onChange } = {}) {
  let mode = DEFAULT_MODE;
  const api = {
    get mode() {
      return mode;
    },
    set(next) {
      if (!MODES.includes(next) || next === mode) return false;
      mode = next;
      if (typeof onChange === 'function') onChange(mode, 'set');
      return true;
    },
    reset() {
      if (mode === DEFAULT_MODE) return false;
      mode = DEFAULT_MODE;
      if (typeof onChange === 'function') onChange(mode, 'reset');
      return true;
    },
  };
  return Object.freeze(api);
}

// The only import-time side effect: register the element and the card picker entry.
if (typeof customElements !== 'undefined' && typeof HTMLElement !== 'undefined') {
  if (!customElements.get(TAG)) customElements.define(TAG, EccoModeShell);
  if (typeof window !== 'undefined') {
    window.customCards = window.customCards || [];
    if (!window.customCards.some((c) => c && c.type === TAG)) {
      window.customCards.push({
        type: TAG,
        name: 'ECCO Mode Shell',
        description: 'One switch between a calm Production view and a Geek view of every available non-secret data point. A presentation toggle only: it never changes what ECCO does.',
        preview: false,
      });
    }
  }
}
