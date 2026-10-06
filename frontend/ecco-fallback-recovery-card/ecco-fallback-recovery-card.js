/*
 * ECCO Fallback / Recovery card (FB-B1 review, FB-B2 guarded Save / Invalidate).
 *
 * One dependency-free ES module: no build step, no npm packages, no network.
 * Home Assistant loads it as a JavaScript module resource; the node tests in
 * ./test import the same file, so the whole pure core below is EXPORTED. The
 * module has exactly one import-time side effect: it registers the custom
 * element (guarded: only when customElements exists and the tag is free) and
 * the card-picker entry.
 *
 * What this card is allowed to do (and nothing else):
 *   - read the firmware's text entities (state strings are `k=v;` lists);
 *   - press the ONE button configured as entities.review_button
 *     (button.press) - a read-only review of the inverter configuration;
 *   - toggle the OPTIONAL input_boolean configured as technical_detail_entity;
 *   - turn the OPTIONAL entities.arm switch on or off, and call the dongle's
 *     execute action with exactly the on-screen candidate (or profile) ID and
 *     its confirmation phrase. Both happen ONLY from a trusted click handler
 *     (event.isTrusted), never from a timer, a render or a state change, and
 *     the card never retries by itself.
 * There is no restore control. The safety authority is the firmware (arm,
 * ID, phrase, one-shot, time limits); the card's own gates only avoid wasting
 * a one-shot.
 *
 * Every entity id comes from the card configuration. No id is spelled here.
 *
 * Layout of this file:
 *   1. constants and configuration validation
 *   2. parsing (k=v strings, slot tuples, masks, obligation vector, B9 text)
 *   3. decoders and text tables (every operator-visible string lives here)
 *   4. state derivation (deriveModel) and countdown maths
 *   5. register table and save-readiness checks
 *   6. HTML renderers (pure: they return strings)
 *   7. the custom element
 */

// ===========================================================================
// 1. constants and configuration validation
// ===========================================================================
export const TAG = 'ecco-fallback-recovery-card';
export const VERSION = '0.2.0';
export const DEFAULT_TITLE = 'Fallback / Recovery';
export const TTL_S = 120; // candidate lifetime published by the firmware (B3 exp counts down from here)
export const MAX_KV_LEN = 200; // hard cap of every k=v entity
export const SOON_S = 45; // at or below: amber "expiring soon"
export const URGENT_S = 15; // below: the dot pulses
export const TICK_MS = 1000;
export const STALE_ANCHOR_S = 600; // stop ticking this long after the last firmware publish
export const DETAIL_STORAGE_KEY = 'ecco-fallback-recovery-card.technical-detail';
export const ARM_TTL_S = 120; // the firmware turns the arm off after this long (its 10 s tick may add up to ~10 s)
export const ARM_PENDING_MS = 4000; // an Arm press waits this long for Home Assistant to echo the switch
export const ACT_PENDING_TIMEOUT_MS = 30000; // a Save request with no answer after this long (the dispatch is bounded at ~24 s)
// FB-B2 (CARD-05): the dongle publishes the arm turning off BEFORE B3 / B9, and Home Assistant may deliver them as separate updates.
// The arm seen off therefore answers a request only after this long, when B3 and B9 have not said anything by then.
export const ARM_OFF_GRACE_MS = 5000;
export const EXECUTE_SERVICE = 'ecco_clock_dongle_fallback_profile_execute'; // esphome.<node>_<api action>
export const U32_MAX = 4294967295;
const HEX16_RE = /^[0-9A-F]{16}$/;

export const REQUIRED_ENTITY_KEYS = Object.freeze([
  'profile_state',
  'summary',
  'review',
  'review_id',
  'review_slots',
  'review_context',
  'saved_slots',
  'saved_context',
  'last_result',
  'review_button',
]);
// FB-B2: `arm` is the fallback-profile arm switch (the card switches it from a user click). The other three are
// the existing write arms of the dongle, read-only here: the firmware refuses a save while one of them is on.
export const OPTIONAL_ENTITY_KEYS = Object.freeze([
  'supervision_stable',
  'supervision_state',
  'ntp_synced',
  'write_lock',
  'configuration_online',
  'arm',
  'free_power_arm',
  'dump_arm',
  'manual_arm',
]);
export const ENTITY_KEYS = Object.freeze([...REQUIRED_ENTITY_KEYS, ...OPTIONAL_ENTITY_KEYS]);

const ENTITY_DOMAIN = Object.freeze({
  profile_state: 'sensor',
  summary: 'sensor',
  review: 'sensor',
  review_id: 'sensor',
  review_slots: 'sensor',
  review_context: 'sensor',
  saved_slots: 'sensor',
  saved_context: 'sensor',
  last_result: 'sensor',
  review_button: 'button',
  supervision_stable: 'binary_sensor',
  supervision_state: 'sensor',
  ntp_synced: 'binary_sensor',
  write_lock: 'binary_sensor',
  configuration_online: 'binary_sensor',
  arm: 'switch',
  free_power_arm: 'switch',
  dump_arm: 'switch',
  manual_arm: 'switch',
});

const ENTITY_ID_RE = /^[a-z0-9_]+\.[a-z0-9_]+$/;

/**
 * Validate and normalise the card configuration. Throws an Error with a
 * message naming the offending key (Home Assistant shows it in the card
 * editor / error card).
 */
export function validateConfig(config) {
  if (!config || typeof config !== 'object' || Array.isArray(config)) {
    throw new Error(`${TAG}: invalid configuration`);
  }
  const ent = config.entities;
  if (!ent || typeof ent !== 'object' || Array.isArray(ent)) {
    throw new Error(`${TAG}: \`entities:\` mapping is required`);
  }
  for (const k of Object.keys(ent)) {
    if (!ENTITY_KEYS.includes(k)) throw new Error(`${TAG}: entities.${k} is not a known entity key`);
  }
  const out = {};
  const usedBy = new Map();
  for (const k of ENTITY_KEYS) {
    const v = ent[k];
    if (v === undefined || v === null || v === '') {
      if (REQUIRED_ENTITY_KEYS.includes(k)) throw new Error(`${TAG}: entities.${k} is required`);
      continue;
    }
    if (typeof v !== 'string' || !ENTITY_ID_RE.test(v)) {
      throw new Error(`${TAG}: entities.${k} must be an entity id such as ${ENTITY_DOMAIN[k]}.example`);
    }
    if (v.split('.')[0] !== ENTITY_DOMAIN[k]) {
      throw new Error(`${TAG}: entities.${k} must be a ${ENTITY_DOMAIN[k]}.* entity`);
    }
    // FB-B2 (CARD-10): one entity id serves ONE key. The card switches entities.arm on from a click; were that id also a write arm
    // of the dongle (or any other key), a mistaken configuration would turn that entity on.
    if (usedBy.has(v)) throw new Error(`${TAG}: entities.${k} repeats the entity id of entities.${usedBy.get(v)}`);
    usedBy.set(v, k);
    out[k] = v;
  }
  let detail = null;
  const te = config.technical_detail_entity;
  if (te !== undefined && te !== null && te !== '') {
    if (typeof te !== 'string' || !ENTITY_ID_RE.test(te) || te.split('.')[0] !== 'input_boolean') {
      throw new Error(`${TAG}: technical_detail_entity must be an input_boolean.* entity`);
    }
    detail = te;
  }
  if (config.show_header !== undefined && typeof config.show_header !== 'boolean') {
    throw new Error(`${TAG}: show_header must be true or false`);
  }
  if (config.title !== undefined && typeof config.title !== 'string') {
    throw new Error(`${TAG}: title must be a string`);
  }
  return Object.freeze({
    title: config.title === undefined ? DEFAULT_TITLE : config.title,
    show_header: config.show_header === undefined ? true : config.show_header,
    entities: Object.freeze(out),
    technical_detail_entity: detail,
  });
}

/** The confirmation phrase of the firmware grammar `^(SAVE|INVALIDATE) [0-9A-F]{16}( REPLACE CORRUPT)?$`. */
export const phraseFor = (action, id, replaceCorrupt = false) => `${action} ${id}${replaceCorrupt ? ' REPLACE CORRUPT' : ''}`;

/**
 * The only service calls this card can ever build:
 *   'review'          button.press on entities.review_button
 *   'detail_toggle'   input_boolean.toggle on technical_detail_entity
 *   'arm_on' / 'arm_off'   switch.turn_on / turn_off on entities.arm
 *   'save' / 'replace_corrupt' / 'invalidate'   the dongle's execute action with
 *       {action, target_id, confirmation}; `params.id` is the on-screen 16-hex ID
 *       (the Review ID for a save, the stored profile's full binding for an invalidate)
 */
export function buildServiceCall(kind, config, params = {}) {
  if (kind === 'review') {
    const id = config && config.entities && config.entities.review_button;
    if (!id) throw new Error(`${TAG}: no review button configured`);
    return { domain: 'button', service: 'press', data: { entity_id: id } };
  }
  if (kind === 'detail_toggle') {
    const id = config && config.technical_detail_entity;
    if (!id) throw new Error(`${TAG}: no technical_detail_entity configured`);
    return { domain: 'input_boolean', service: 'toggle', data: { entity_id: id } };
  }
  if (kind === 'arm_on' || kind === 'arm_off') {
    const id = config && config.entities && config.entities.arm;
    if (!id) throw new Error(`${TAG}: no arm entity configured`);
    return { domain: 'switch', service: kind === 'arm_on' ? 'turn_on' : 'turn_off', data: { entity_id: id } };
  }
  if (kind === 'save' || kind === 'replace_corrupt' || kind === 'invalidate') {
    if (!(config && config.entities && config.entities.arm)) throw new Error(`${TAG}: no arm entity configured`);
    const id = params && params.id;
    if (typeof id !== 'string' || !HEX16_RE.test(id)) throw new Error(`${TAG}: a 16 hex digit ID is required`);
    const action = kind === 'invalidate' ? 'INVALIDATE' : 'SAVE';
    return {
      domain: 'esphome',
      service: EXECUTE_SERVICE,
      data: { action, target_id: id, confirmation: phraseFor(action, id, kind === 'replace_corrupt') },
    };
  }
  throw new Error(`${TAG}: unknown service call kind`);
}

/**
 * Defence in depth: true only for the allowed calls against the configured entities. The execute call is allowed
 * only with exactly the keys action, target_id and confirmation, an action of SAVE or INVALIDATE, an upper-case
 * 16-hex target and the phrase built from those same two values (REPLACE CORRUPT only with SAVE).
 */
export function isAllowedServiceCall(call, config) {
  if (!call || typeof call !== 'object' || !config || !config.entities) return false;
  // FB-B2 (CARD-10): the arm entity is never also another configured entity (validateConfig refuses it; this guards a config object
  // that did not come from validateConfig): switching it on must never switch on a write arm of the dongle
  const armIsOwn = !config.entities.arm || Object.entries(config.entities).every(([k, v]) => k === 'arm' || v !== config.entities.arm);
  const data = call.data && typeof call.data === 'object' && !Array.isArray(call.data) ? call.data : null;
  if (!data) return false;
  const keys = Object.keys(data);
  const onlyEntity = keys.length === 1 && keys[0] === 'entity_id';
  if (call.domain === 'button' && call.service === 'press') {
    return onlyEntity && data.entity_id === config.entities.review_button;
  }
  if (call.domain === 'input_boolean' && call.service === 'toggle') {
    return onlyEntity && !!config.technical_detail_entity && data.entity_id === config.technical_detail_entity;
  }
  if (call.domain === 'switch' && (call.service === 'turn_on' || call.service === 'turn_off')) {
    if (!armIsOwn) return false;
    return onlyEntity && !!config.entities.arm && data.entity_id === config.entities.arm;
  }
  if (call.domain === 'esphome' && call.service === EXECUTE_SERVICE) {
    if (!armIsOwn) return false;
    if (!config.entities.arm) return false;
    if (keys.length !== 3 || !['action', 'target_id', 'confirmation'].every((k) => keys.includes(k))) return false;
    const { action, target_id: id, confirmation } = data;
    if (action !== 'SAVE' && action !== 'INVALIDATE') return false;
    if (typeof id !== 'string' || !HEX16_RE.test(id)) return false;
    if (confirmation === phraseFor(action, id, false)) return true;
    return action === 'SAVE' && confirmation === phraseFor(action, id, true);
  }
  return false;
}

// ===========================================================================
// 2. parsing
// ===========================================================================
export const KV_KEYS = Object.freeze({
  summary: Object.freeze(['g', 'id', 'at', 'ld', 'df', 'w', 'hw', 'op', 'why', 'werr', 'us']),
  review: Object.freeze(['st', 'prior', 'exp', 'warn', 'obl', 'latch', 'sv']),
  slots: Object.freeze(['v', 'g', '244', '1', '2', '3', '4', '5', '6', 'dx']),
  context: Object.freeze(['v', '232', '243', '248', 'ring', '230', '245', '247', 'dc', 'di']),
  savedSlots: Object.freeze(['v', 'g', '244', '1', '2', '3', '4', '5', '6', 'dx', 'b']),
  savedContext: Object.freeze(['v', '232', '243', '248', 'ring', '230', '245', '247', 'dc', 'di', 'b']),
});

export const isAvailable = (s) => typeof s === 'string' && s !== '' && s !== 'unavailable' && s !== 'unknown';

/**
 * Own-property lookup for every text table that is indexed by a string taken from an entity. A plain
 * `TABLE[key]` would answer `constructor`, `toString` or `__proto__` with a function or an object from
 * Object.prototype; this answers undefined for anything that is not a key of the table itself.
 */
export const own = (table, key) => (typeof key === 'string' && Object.hasOwn(table, key) ? table[key] : undefined);

/**
 * Parse a `k=v;k=v` string. Returns null (treated as "unavailable") when the
 * value is not a string, is empty, is longer than 200 characters, has a part
 * without `key=value`, repeats a key, or lacks one of `required`.
 */
export function parseKv(s, required = []) {
  if (typeof s !== 'string' || s.length === 0 || s.length > MAX_KV_LEN) return null;
  const parts = s.split(';');
  if (parts.length > 1 && parts[parts.length - 1] === '') parts.pop();
  const o = {};
  for (const part of parts) {
    const i = part.indexOf('=');
    if (i < 1) return null;
    const k = part.slice(0, i);
    const v = part.slice(i + 1);
    if (!/^[A-Za-z0-9]+$/.test(k) || v === '') return null;
    if (Object.prototype.hasOwnProperty.call(o, k)) return null;
    o[k] = v;
  }
  for (const k of required) if (!Object.prototype.hasOwnProperty.call(o, k)) return null;
  return o;
}

export function parseU(v, max = 0xffffffff) {
  if (typeof v !== 'string' || !/^\d{1,10}$/.test(v)) return null;
  const n = Number(v);
  return n <= max ? n : null;
}

export function parseHex(v) {
  if (typeof v !== 'string' || !/^[0-9A-Fa-f]{1,8}$/.test(v)) return null;
  return parseInt(v, 16);
}

/** `HHMM/W/SOC/SRC`: four decimal fields (HHMM is %04u; SRC is the FULL register word). */
export function parseSlotTuple(t) {
  if (typeof t !== 'string') return null;
  const m = /^(\d{4,5})\/(\d{1,5})\/(\d{1,5})\/(\d{1,5})$/.exec(t);
  if (!m) return null;
  const [hhmm, w, soc, src] = m.slice(1).map(Number);
  if (hhmm > 65535 || w > 65535 || soc > 65535 || src > 65535) return null;
  return { hhmm, w, soc, src };
}

/** B5 (candidate) / B7 (saved, `saved=true`, adds `b`). */
export function parseSlotsEntity(s, saved = false) {
  const o = parseKv(s, saved ? KV_KEYS.savedSlots : KV_KEYS.slots);
  if (!o) return null;
  return {
    v: o.v,
    g: o.g === '-' ? null : parseU(o.g),
    reg244: o['244'] === '-' ? null : parseU(o['244'], 65535),
    slots: [1, 2, 3, 4, 5, 6].map((n) => (o[String(n)] === '-' ? null : parseSlotTuple(o[String(n)]))),
    dx: o.dx,
    b: saved ? o.b : null,
  };
}

/** B6 (candidate) / B8 (saved, `saved=true`, adds `b`). */
export function parseContextEntity(s, saved = false) {
  const o = parseKv(s, saved ? KV_KEYS.savedContext : KV_KEYS.context);
  if (!o) return null;
  const hex = (x) => (x === '-' ? null : parseHex(x));
  return {
    v: o.v,
    r232: hex(o['232']),
    r243: o['243'] === '-' ? null : parseU(o['243'], 65535),
    r248: hex(o['248']),
    ring: o.ring,
    r230: o['230'] === '-' ? null : parseU(o['230'], 65535),
    r245: o['245'] === '-' ? null : parseU(o['245'], 65535),
    r247: hex(o['247']),
    dc: o.dc,
    di: o.di,
    b: saved ? o.b : null,
  };
}

// ---- masks -----------------------------------------------------------------
export const DX_BITS = 0x7ffff; // bit0 244; bits1-6 256-261; bits7-12 268-273; bits13-18 274-279
export const DC_BITS = 0x1ff; // bit0 232.b0; bit1 243; bit2 248.b0; bits3-8 250-255
export const DI_BITS = 0x1f; // bit0 230; bit1 245; bit2 247; bit3 232 b1-15; bit4 248 b1-15

/** True/false for one bit of a hex mask, null when the mask is `-` or malformed. */
export function maskBit(h, bit) {
  const n = parseHex(h);
  return n === null ? null : ((n >>> bit) & 1) === 1;
}

export function popcount(h, validBits) {
  const n = parseHex(h);
  if (n === null) return 0;
  let x = (n & validBits) >>> 0;
  let c = 0;
  while (x) {
    c += x & 1;
    x >>>= 1;
  }
  return c;
}

/**
 * Per-register difference (candidate vs the saved profile) read from dx/dc/di.
 * `core` comes from dx/dc (what the live match is about); `info` from di
 * (information-only registers and the upper bits of 232/248). Either is null
 * when its mask is `-` (no authentic stored profile, or no candidate).
 */
export function regDiff(reg, dx, dc, di) {
  let core = null;
  let info = null;
  if (reg === 244) core = maskBit(dx, 0);
  else if (reg >= 256 && reg <= 261) core = maskBit(dx, 1 + reg - 256);
  else if (reg >= 268 && reg <= 273) core = maskBit(dx, 7 + reg - 268);
  else if (reg >= 274 && reg <= 279) core = maskBit(dx, 13 + reg - 274);
  else if (reg === 232) {
    core = maskBit(dc, 0);
    info = maskBit(di, 3);
  } else if (reg === 243) core = maskBit(dc, 1);
  else if (reg === 248) {
    core = maskBit(dc, 2);
    info = maskBit(di, 4);
  } else if (reg >= 250 && reg <= 255) core = maskBit(dc, 3 + reg - 250);
  else if (reg === 230) info = maskBit(di, 0);
  else if (reg === 245) info = maskBit(di, 1);
  else if (reg === 247) info = maskBit(di, 2);
  return { core, info };
}

/** Combined verdict for the raw table: true/false, or null when nothing is comparable. */
export function regDiffAny(reg, dx, dc, di) {
  const { core, info } = regDiff(reg, dx, dc, di);
  if (core === null && info === null) return null;
  return core === true || info === true;
}

// ---- obligation vector / latch / saveability -------------------------------
export const OBL_ORDER = Object.freeze(['FP', 'DP', 'R4', 'MT', 'FS', 'BUS']);
export const DOMAIN_LABEL = Object.freeze({
  FP: 'Free Power',
  DP: 'Dump to Grid',
  R4: 'Register 244 test',
  MT: 'Manual TOU',
  FS: 'Failback record',
  BUS: 'Inverter bus',
});
const OBL_CLEAR = new Set(['CM', 'CA', 'CN', 'CR', 'OK']);
const OBL_TRANSIENT = new Set(['AC', 'ST', 'RR', 'PC', 'EN', 'IF']);
export const KIND_TEXT = Object.freeze({
  CM: 'clear marker',
  CA: 'no record stored',
  CN: 'no durable state',
  CR: 'clear (memory only)',
  OK: 'idle',
  AC: 'is running',
  ST: 'is starting',
  RR: 'must restore first',
  PC: 'restore verified, durable clear pending',
  EN: 'is restoring',
  IF: 'operation in flight',
  ON: 'needs your decision',
  UR: 'recovery state unreadable',
  MC: 'recovery metadata corrupt',
  CT: 'recovery metadata corrupt',
  ML: 'recovery metadata corrupt',
  DV: 'stored state disagrees with memory',
  LK: 'inverter write lock stuck',
  BL: 'durable state not loaded yet',
  NP: 'not yet checked',
  BY: 'busy',
});

/**
 * The obligation vector is exactly six `DOM:KIND` entries in the fixed order FP,DP,R4,MT,FS,BUS. Anything
 * else (a short, long, duplicated, reordered or unknown-domain vector) is not a vector this card can judge,
 * so it is null and the readiness check that depends on it reads "unknown" rather than "clear".
 */
export function parseObl(s) {
  if (typeof s !== 'string' || s === '-' || s === '') return null;
  const parts = s.split(',');
  if (parts.length !== OBL_ORDER.length) return null;
  const out = [];
  for (let i = 0; i < parts.length; i++) {
    const m = /^([A-Z0-9]{2,3}):([A-Z0-9]{2})$/.exec(parts[i]);
    if (!m || m[1] !== OBL_ORDER[i]) return null;
    out.push({ d: m[1], k: m[2] });
  }
  return out;
}

/** 'clear' | 'transient' | 'lockout' (anything unknown fails closed as a lockout). */
export function oblKindClass(k) {
  if (OBL_CLEAR.has(k)) return 'clear';
  if (OBL_TRANSIENT.has(k)) return 'transient';
  return 'lockout';
}

export function parseLatch(s) {
  if (typeof s !== 'string' || s === '-' || s === '') return [];
  return s.split(',').filter(Boolean);
}

export function parseSv(s) {
  if (s === '-') return { kind: 'none', codes: [], more: 0 };
  if (s === 'OK') return { kind: 'ok', codes: [], more: 0 };
  const m = /^NO:([A-Z0-9]+(?:,[A-Z0-9]+)*)(?:\+(\d+))?$/.exec(typeof s === 'string' ? s : '');
  if (!m) return { kind: 'invalid', codes: [], more: 0 };
  return { kind: 'no', codes: m[1].split(','), more: m[2] ? Number(m[2]) : 0 };
}

// ---- B9 (last action-result) -----------------------------------------------
const B9_SEED = 'No Fallback Profile action since boot';

/**
 * Classify the B9 text by its prefix. `detail` is everything after the first
 * ' - ' (verbatim), `mismatch` the first differing register of a pass
 * mismatch, `block` the FC03 block named by a read failure.
 */
export function parseB9(text) {
  const raw = typeof text === 'string' ? text : '';
  const idx = raw.indexOf(' - ');
  const detail = idx >= 0 ? raw.slice(idx + 3) : '';
  let kind = 'other';
  if (raw === B9_SEED) kind = 'seed';
  else if (/^review in progress \(read-only\)/.test(raw)) kind = 'reading';
  else if (/^CANDIDATE READY/.test(raw)) kind = 'ready';
  else if (/^CANDIDATE NOT SAVEABLE/.test(raw)) kind = 'notsaveable';
  else if (/^REVIEW REFUSED/.test(raw)) kind = 'refused';
  else if (/^REVIEW NOT COMPLETED/.test(raw)) kind = 'notcompleted';
  else if (/^REVIEW EXPIRED/.test(raw)) kind = 'expired';
  else if (/^REVIEW CLEARED/.test(raw)) kind = 'cleared';
  else if (/^INTERNAL/.test(raw)) kind = 'internal';
  // FB-B2 families (Save / Invalidate). The progress line is lower case; every other prefix is a fixed upper-case word set.
  else if (/^save in progress/.test(raw)) kind = 'saveprogress';
  else if (/^SAVED\b/.test(raw)) kind = 'saved';
  else if (/^SAVE REFUSED/.test(raw)) kind = 'saverefused';
  else if (/^SAVE NOT COMMITTED/.test(raw)) kind = 'savenotcommitted';
  else if (/^SAVE OUTCOME UNKNOWN/.test(raw)) kind = 'saveunknown';
  else if (/^INVALIDATED\b/.test(raw)) kind = 'invalidated';
  else if (/^INVALIDATE REFUSED/.test(raw)) kind = 'invalidaterefused';
  else if (/^INVALIDATE NOT COMMITTED/.test(raw)) kind = 'invalidatenotcommitted';
  else if (/^INVALIDATE OUTCOME UNKNOWN/.test(raw)) kind = 'invalidateunknown';
  else if (/^(REFUSED|RESTORE REFUSED|ACKNOWLEDGE REFUSED)\b/.test(raw)) kind = 'actionrefused';
  const mm = /register (\d+): (0x[0-9A-Fa-f]+|\d+) then (0x[0-9A-Fa-f]+|\d+)/.exec(raw);
  const bm = /registers? (230\/3|241\/53)/.exec(raw);
  const gm = /\bgeneration (\d{1,10})\b/.exec(raw);
  const nm = /\bnow INVALIDATED g(\d{1,10})\b/.exec(raw);
  return {
    raw,
    kind,
    detail,
    mismatch: mm ? { reg: Number(mm[1]), a: mm[2], b: mm[3] } : null,
    block: bm ? bm[1] : null,
    busy: /bus stayed busy/.test(raw),
    gen: gm ? parseU(gm[1]) : null, // SAVED: the generation saved; INVALIDATED: the generation that was invalidated
    newGen: nm ? parseU(nm[1]) : null, // INVALIDATED: the generation of the invalidated record
    witness: /witness advanced|generation record advanced/.test(raw), // the profile record was not written but its witness was
  };
}

const ACT_OF_KIND = Object.freeze({
  saveprogress: ['save', 'progress'],
  saved: ['save', 'saved'],
  saverefused: ['save', 'refused'],
  savenotcommitted: ['save', 'notcommitted'],
  saveunknown: ['save', 'unknown'],
  invalidated: ['invalidate', 'invalidated'],
  invalidaterefused: ['invalidate', 'refused'],
  invalidatenotcommitted: ['invalidate', 'notcommitted'],
  invalidateunknown: ['invalidate', 'unknown'],
  actionrefused: ['other', 'refused'],
});

/**
 * The last Save / Invalidate outcome, or null when B9 is not one. `verified` is the card's own consistency check of
 * "saved and verified this boot": the profile class and generation the dongle publishes (B1, B2) agree with the B9 text, the
 * witness reads OK, no storage error is reported (werr) and the last operation is the matching one (op: SAVE, or RC for a REPLACE
 * CORRUPT save; INV for an invalidate). `b2` is the parsed summary (null: nothing can be verified).
 */
export function deriveAct(b9, b1, g, b2 = null) {
  const f = own(ACT_OF_KIND, b9.kind);
  if (!f) return null;
  const [family, outcome] = f;
  let verified = false;
  const storageOk = !!b2 && b2.w === 'OK' && b2.werr === '-';
  if (outcome === 'saved') {
    verified = b1 === 'VALID' && g !== null && b9.gen !== null && b9.gen === g && storageOk && (b2.op === 'SAVE' || b2.op === 'RC');
  }
  if (outcome === 'invalidated') {
    verified = b1 === 'INVALIDATED' && g !== null && b9.newGen !== null && b9.newGen === g && storageOk && b2.op === 'INV';
  }
  return {
    family,
    outcome,
    tone: b9Tone(b9.raw),
    detail: b9.detail || b9.raw,
    gen: b9.gen,
    newGen: b9.newGen,
    witness: outcome === 'notcommitted' && b9.witness,
    verified,
  };
}

/** Colour class of the last-action line (S5 outcome tone classes). */
export function b9Tone(text) {
  const t = typeof text === 'string' ? text : '';
  if (/^(CANDIDATE READY|SAVED|INVALIDATED)/.test(t)) return 'ok';
  if (/^(SAVE NOT COMMITTED|SAVE OUTCOME UNKNOWN|INVALIDATE NOT COMMITTED|INVALIDATE OUTCOME UNKNOWN|INTERNAL)/.test(t)) {
    return 'bad';
  }
  if (/^(CANDIDATE NOT SAVEABLE|REVIEW REFUSED|REVIEW NOT COMPLETED|SAVE REFUSED|INVALIDATE REFUSED|REFUSED|RESTORE REFUSED|ACKNOWLEDGE REFUSED)/.test(t)) {
    return 'warn';
  }
  return 'neutral';
}

// ===========================================================================
// 3. decoders and operator text tables
// ===========================================================================
export const pad2 = (n) => String(n).padStart(2, '0');
export const mmss = (s) => `${Math.floor(s / 60)}:${pad2(s % 60)}`;
export const hex4 = (n) => n.toString(16).toUpperCase().padStart(4, '0');

const DEC244 = Object.freeze({ 0: 'Allow Export', 1: 'Essentials', 2: 'Zero Export' });
const DEC243 = Object.freeze({ 0: 'Battery First', 1: 'Load First' });
const decNum = (table, v) => (Number.isInteger(v) && Object.hasOwn(table, v) ? table[v] : `unrecognised (${v})`);
export const dec244 = (v) => decNum(DEC244, v);
export const dec243 = (v) => decNum(DEC243, v);
export const bit0 = (v) => (v === null || v === undefined ? null : (v & 1) === 1);

/** Register 274-279: bits 0-1 source, bits 2-4 mode (one-hot 4 / 8 / 16), anything else shown raw. */
export function decSrc(w) {
  const src = ['None', 'Grid', 'Generator', 'Grid + Generator'][w & 3];
  const m = w & 0x1c;
  const known = { 0: 'None', 4: 'General', 8: 'Backup', 16: 'Charge' }[m];
  const rawNeeded = known === undefined || (w & ~0x1f) !== 0;
  return {
    src,
    mode: known === undefined ? 'unrecognised' : known,
    raw: rawNeeded ? `0x${hex4(w)}` : null,
  };
}
export const modeText = (d) => (d.raw ? `${d.mode} raw ${d.raw}` : d.mode);

export function hhmmValid(v) {
  return Number.isInteger(v) && v >= 0 && v <= 2359 && Math.floor(v / 100) <= 23 && v % 100 <= 59;
}
export function hhmmText(v) {
  if (v === null || v === undefined) return '—';
  return hhmmValid(v) ? `${pad2(Math.floor(v / 100))}:${pad2(v % 100)}` : `${String(v).padStart(4, '0')} (invalid)`;
}

/** Format a register word for the raw table: 232 / 248 / 247 in hex, everything else decimal. */
export function formatWord(reg, v) {
  if (v === null || v === undefined) return '—';
  return reg === 232 || reg === 248 || reg === 247 ? `0x${hex4(v)}` : String(v);
}

/** Ring rule used by the firmware (W6): every gap > 0 and the gaps sum to 1440. */
export function ringValid(starts) {
  if (starts.some((v) => !hhmmValid(v))) return false;
  const m = starts.map((v) => Math.floor(v / 100) * 60 + (v % 100));
  let sum = 0;
  for (let i = 0; i < m.length; i++) {
    const d = (m[(i + 1) % m.length] - m[i] + 1440) % 1440;
    if (d <= 0) return false;
    sum += d;
  }
  return sum === 1440;
}

export const CLASS_NAMES = Object.freeze([
  'NOT_CAPTURED',
  'VALID',
  'INVALIDATED',
  'CORRUPT',
  'CORRUPT_DOMAIN',
  'UNREADABLE',
  'PROFILE_LOST',
  'SAVE_UNCONFIRMED',
  'PROFILE_STALE',
]);
const KNOWN_CLASSES = new Set(CLASS_NAMES);
const UNUSABLE_CLASSES = new Set(['CORRUPT', 'CORRUPT_DOMAIN', 'UNREADABLE', 'PROFILE_LOST', 'SAVE_UNCONFIRMED', 'PROFILE_STALE']);
// FB-B2 adds SAVING. INVALIDATING (an invalidate is one synchronous step, never observable) and every FB-E value
// (PLAN_READY, PLAN_NOT_POSSIBLE, APPLYING) stay unrecognised: a status this card does not know is never guessed.
const KNOWN_ST = new Set(['IDLE', 'READING', 'CANDIDATE_READY', 'CANDIDATE_NOT_SAVEABLE', 'SAVING']);

export const LD_TEXT = Object.freeze({
  OK: 'record read',
  ABS: 'no record stored',
  WSZ: 'record has the wrong size',
  RERR: 'storage read error',
  UNAV: 'storage unavailable',
});
export const DF_TEXT = Object.freeze({
  MAGIC: 'wrong record marker',
  SCHEMA: 'unsupported record version',
  SIZE: 'wrong record length',
  BINDING: 'integrity check mismatch',
  RESERVED: 'reserved bytes not zero',
  FLAGS: 'unsupported flag bits',
  GEN: 'invalid generation',
  DOMAIN: 'value outside the supported range',
});
export const W_TEXT = Object.freeze({
  OK: 'valid',
  LAG: 'lagging behind the record',
  MISS: 'missing',
  CORR: 'damaged',
  UNR: 'unreadable',
  ABS: 'absent',
});

/** Card 1 sentences for unusable classes (S5 S-5, S-6a to S-6d, plus the stale record). */
export function unusableSentence(b1, hw) {
  switch (b1) {
    case 'SAVE_UNCONFIRMED':
      return 'The last save could not be confirmed. Restart the dongle when no temporary operation is active; saving stays disabled until then.';
    case 'UNREADABLE':
      return 'The stored profile could not be read (storage read error). Saving is disabled until the dongle next restarts.';
    case 'CORRUPT':
      return 'The stored profile is damaged. It cannot be used, and it is never overwritten from the dashboard.';
    case 'PROFILE_LOST':
      return hw === null || hw === undefined
        ? 'The saved profile is missing from storage. Review and save a new known-good profile.'
        : `The saved profile (last known generation ${hw}) is missing from storage. Review and save a new known-good profile.`;
    case 'PROFILE_STALE':
      return 'Saved profile is out of step with its record - review and save again.';
    default: // CORRUPT_DOMAIN
      return 'The stored profile holds values outside the supported range and cannot be used. Review and save a new known-good profile.';
  }
}

/**
 * Live Match sentence when the stored profile is unusable (card 2, any unusable class): Live Match reports no match
 * and says why, instead of the plain "no saved profile". The firmware computes the difference masks only against a
 * TRUSTED stored profile (an authentic record whose effective class is not UNREADABLE), so for UNREADABLE (and for a
 * record that is not authentic) nothing was compared; the Summary card says that separately (notComparedNote).
 */
export function untrustedSentence(b1) {
  switch (b1) {
    case 'UNREADABLE':
      return 'The stored profile could not be read, so it cannot be trusted and no match is reported.';
    case 'PROFILE_LOST':
      return 'The saved profile is missing from storage, so there is nothing to compare against.';
    default:
      return `The stored profile is ${b1} and cannot be used, so no match is reported.`;
  }
}

export const SENTENCE = Object.freeze({
  notReporting: 'The ECCO dongle is not reporting its Fallback Profile status.',
  entitiesUnavailable: 'Fallback Profile entities are not available. Check firmware version.',
  notSaved: 'No known-good profile saved yet. Review your current configuration and save it.',
  invalidated: 'The saved profile was invalidated and will not be used. Review and save a new known-good profile.',
  noSavedToCompare: 'No saved profile to compare against.',
  notComparable: 'Not compared: the saved profile is not trusted, or the firmware reported no comparison.',
  pressReview: 'Press Review Current Configuration to compare. Live comparison without a review arrives in FB-B3.',
  reviewAvailable: 'Read the current inverter configuration and build a temporary candidate.',
  reviewReading: 'Read-only. Two passes, four reads, then a compare. Usually 2–3 s.',
  notSaveable: 'Values read cleanly but cannot be saved in Fallback V1. See the candidate card.',
  expired: 'The candidate expired after 120 s. Review again when ready.',
  noCandidate: 'Press Review Current Configuration to read the inverter and build one. Candidates live for 120 s in RAM only.',
  recoveryReserved: 'Recovery controls arrive in later stages. Nothing here is active.',
  futureRecovery: 'These controls arrive in later stages (FB-E restore, FB-F acknowledge).',
  reviewCaption: 'Reads the inverter twice (4 reads). Changes nothing.',
  saving: 'Re-reading the inverter before commit.',
});

/**
 * Every operator string of the guarded Save / Invalidate flow that is not built from live values. The wording rules
 * of the card (no phrase the Energy Actions card classifies as busy or recovery, nothing starting with the words
 * those classifiers key on, and the two forbidden words) are pinned by the tests over this table and over every
 * rendered scenario, in every flow state.
 */
export const FLOW_TEXT = Object.freeze({
  armSave: 'Arm Save',
  armInvalidate: 'Arm Invalidate',
  arming: 'Arming…',
  save: 'Save Fallback Profile',
  replace: 'Replace damaged profile',
  invalidate: 'Invalidate Profile',
  cancel: 'Cancel',
  turnOff: 'Turn arm off',
  armCaption: 'Arm turns off by itself after 2 min, and whenever you press Review, Save or Invalidate.',
  armUnavailable: 'The arm entity is unavailable',
  armAlreadyOn: 'The arm is already on',
  armRequested: 'Arm requested',
  notSetUp: 'Saving is not set up on this dashboard: the arm entity is missing from the card configuration.',
  invalidateNotSetUp: 'Invalidate is not set up on this dashboard: the arm entity is missing from the card configuration.',
  armNotOn: 'ECCO Fallback Profile Arm is not on',
  armExpiring: 'The arm is expiring - turn it off and arm again',
  armCancelling: 'The arm is being turned off',
  candidateExpiring: 'The candidate is expiring: review again',
  titleSave: 'Confirm save',
  titleReplace: 'Confirm replacing a damaged profile',
  titleInvalidate: 'Confirm invalidate',
  introSave: 'This saves the reviewed values as the known-good profile. The inverter is not changed.',
  introReplace:
    'This replaces a damaged saved profile after logging its raw bytes. It does not erase storage and does not change the inverter.',
  introInvalidate:
    'This makes the saved profile unusable. It is kept for reference but will never be used until you save a new one. The inverter is not changed.',
  discardsCandidate: 'This also discards the current candidate.',
  oneShot: 'Every attempt turns the arm off and uses up the candidate, even when it is refused.',
  oneShotInvalidate: 'Every attempt turns the arm off, even when it is refused.',
  sent: 'Request sent - waiting for the dongle.',
  running: 'Saving - the dongle is re-reading the inverter and writing the profile record.',
  doNotRepeat: 'Do not press Save again. The result appears under Last action.',
  invalidateSent: 'Invalidate request sent - waiting for the dongle.',
  noResult: 'No result yet. Check Last action before trying again; do not press Save twice.',
  noResultInvalidate: 'No result yet. Check Last action before trying again; do not press Invalidate twice.',
  notAccepted:
    'Home Assistant did not accept the request, so it may not have reached the dongle. Check Last action before trying again.',
  changedOnScreen: 'The ID on screen changed. Check the new ID, then confirm again.',
  armNoEcho: 'The arm did not turn on. Check the connection and try again.',
  notAUserClick: 'Only a click on the button can start this.',
  noConfirmId: 'Confirm the ID shown on screen first.',
  armForInvalidate: 'The arm is set for Invalidate (see the Saved profile card). Turn it off to save instead.',
  armIsOn: 'Arm is on.',
  armElsewhere: 'Arm was turned on elsewhere.',
  armElsewhereWhy: 'The arm was not turned on from this card. Turn it off and arm again.',
  armSpent: 'This arm was already used by your request.',
  armSpentWhy: 'The arm was used by your request. Turn it off and arm again.',
  candValuesMissing: 'The candidate values are not available on this dashboard, so they cannot be checked before saving',
  summaryMissing: 'The saved-profile summary is not available, so the generation to be written cannot be shown',
  generationUnknown: 'The generation to be written cannot be shown: the saved-profile summary is not complete.',
  inFlight: 'another Fallback Profile operation is in progress',
  noCandidate: 'no saveable candidate - press Review Current Configuration first',
  heartbeat:
    'Home Assistant heartbeat is not stable; wait until the dashboard shows it healthy, then review and save again',
  ntp: 'clock not NTP-synchronised this boot; the capture time would be untrusted',
  armsOn: 'a Free Power / Dump to Grid / Manual Configuration write arm is on; finish or turn it off first',
  busBusy: 'another inverter transaction is in progress; try again shortly',
  checkedAtSave: 'not shown on this dashboard; the dongle checks it when you save',
  savedOk: 'Saved and verified this boot',
  savedUnverified: 'The dongle reports the save. Waiting for the saved profile to update.',
  saveRefusedTail:
    'Nothing was saved and the inverter was not changed. The arm was turned off: review again before trying again.',
  saveNotCommitted: 'Nothing changed: the previous profile is still in place. Review again before trying again.',
  saveWitness:
    'The stored profile is now out of step with its generation record and cannot be used. Review and save again.',
  saveUnknown:
    'Do not press Save again. If a temporary operation (Free Power, Dump to Grid, register 244 test) is active or needs a decision, do not restart the dongle. Otherwise restart the dongle to find out what was stored.',
  invalidatedOk: 'Invalidated: the profile can no longer be used. Save a new profile to re-enable it.',
  invalidatedUnverified: 'The dongle reports the invalidation. Waiting for the saved profile to update.',
  invalidateRefusedTail: 'Nothing was changed. The arm was turned off: arm again to try again.',
  invalidateNotCommitted: 'Nothing changed: the saved profile is still VALID.',
  invalidateWitness:
    'The profile record was not written, but its generation record advanced: the stored profile is now out of step and cannot be used.',
  invalidateUnknown:
    'Treat the profile as unusable. If a temporary operation (Free Power, Dump to Grid, register 244 test) is active or needs a decision, do not restart the dongle. Otherwise restart the dongle to find out what was stored.',
  actionRefused: 'The dongle refused an action this card does not send.',
});

export const WARNING_TEXT = Object.freeze({
  W1: 'Looks like a Free Power overlay - confirm this is your normal setup.',
  W2: 'All six slot powers are equal and at most 3000 W - this resembles Dump to Grid residue; confirm.',
  W3: "TOU schedule (248) is OFF: this profile's slot settings are inactive on the inverter.",
  W4: 'Grid charging is globally disabled (232) while slots select Grid.',
  W5: 'A slot start is off the 5-minute grid.',
  W6: 'Slot times are not a valid 24 h ring (duplicate or out-of-order start).',
});
export const warnW5 = (n, start) => `Slot ${n} start ${hhmmText(start)} is off the 5-minute grid.`;

/**
 * Warning rows for B3 `warn`. W5 carries no slot number, so the off-grid
 * slots are found from the candidate's own slot starts; when none can be
 * identified the generic text is used.
 */
export function warningRows(warn, slots) {
  const codes = warn && warn !== '-' ? warn.split(',') : [];
  const rows = [];
  for (const code of codes) {
    if (code === 'W5') {
      const off = [];
      (slots || []).forEach((s, i) => {
        if (s && hhmmValid(s.hhmm) && s.hhmm % 5 !== 0) off.push(warnW5(i + 1, s.hhmm));
      });
      if (off.length) off.forEach((text) => rows.push({ code, text }));
      else rows.push({ code, text: WARNING_TEXT.W5 });
    } else if (own(WARNING_TEXT, code)) {
      rows.push({ code, text: own(WARNING_TEXT, code) });
    } else {
      rows.push({ code, text: `Warning ${code} is not recognised by this card.` });
    }
  }
  return rows;
}

/**
 * Operator text for one `sv=NO:` code. `ctx` carries the candidate's own
 * values (reg244, reg243, slots) so the text can name them; a missing value
 * simply drops that fragment.
 */
export function blockerText(code, ctx = {}) {
  const m = /^(244X|243X|PWRL|PWRH|SOCH|SRCG|MODE|BITS|HHMM)([1-6])?$/.exec(code);
  if (!m) return `Not saveable: code ${code} is not recognised by this card.`;
  const [, base, nStr] = m;
  const n = nStr ? Number(nStr) : null;
  const slot = n && ctx.slots ? ctx.slots[n - 1] : null;
  const val = (x, unit) => (x === null || x === undefined ? '' : ` ${x}${unit}`);
  switch (base) {
    case '244X':
      return `Export mode is ${
        ctx.reg244 === null || ctx.reg244 === undefined ? 'not a Zero Export value' : dec244(ctx.reg244)
      }: Fallback V1 can only save a Zero Export profile (244 = 2).`;
    case '243X':
      return `Energy-management model${val(ctx.reg243, '')} is not recognised (0 Battery First, 1 Load First).`;
    case 'PWRL':
      return `Slot ${n} power${val(slot && slot.w, ' W')} is below the 500 W V1 minimum.`;
    case 'PWRH':
      return `Slot ${n} power${val(slot && slot.w, ' W')} is above 8000 W (or above this site's configured ceiling).`;
    case 'SOCH':
      return `Slot ${n} target SOC${val(slot && slot.soc, ' %')} is above 100 %.`;
    case 'SRCG':
      return `Slot ${n} source Generator / Grid + Generator is unsupported in V1.`;
    case 'MODE':
      return `Slot ${n} mode General / Backup / Charge is unsupported in V1.`;
    case 'BITS':
      return slot
        ? `Slot ${n} has undecoded bits 0x${hex4(slot.src & ~0x1f & 0xffff)} set.`
        : `Slot ${n} has undecoded bits set.`;
    default: // HHMM
      return `Slot ${n} start${slot ? ` ${String(slot.hhmm).padStart(4, '0')}` : ''} is not a valid HH:MM time.`;
  }
}

/** FB-B2 (CARD-01): the heartbeat failure that names the state, shared by check 5 and the save gate. The state is entity text: it is escaped where it is printed. */
export const supervisionStateText = (state) => `Supervision state is ${state}, not SUPERVISED`;
export const priorBlockerText = (prior) =>
  `Stored profile is ${prior}: saving stays disabled until the dongle restarts.`;
export const priorReplaceNote = (prior) =>
  `Stored profile is ${prior}: saving replaces it and needs the REPLACE CORRUPT confirmation.`;
export const FALLBACK_BLOCKER = 'The firmware reports this candidate as not saveable.';
export const SV_UNCONFIRMED_BLOCKER = 'The firmware did not confirm that the profile values are valid for Fallback V1.';
export const NO_ID_BLOCKER = 'The candidate has no valid ID, so it cannot be saved.';
export const PRIOR_UNKNOWN_BLOCKER = 'The stored profile class is not recognised - check that firmware and dashboard versions match.';
export const EXPIRING_TEXT = 'Expiring - waiting for the firmware';
export const moreBlockers = (n) => `${n} more reason${n === 1 ? '' : 's'} not listed (see technical detail).`;

// ===========================================================================
// 4. state derivation and countdown maths
// ===========================================================================
function strOf(E, k) {
  return typeof E[k] === 'string' ? E[k] : undefined;
}

/**
 * Turn the entity state strings (keyed by the configuration keys) into the
 * view model every renderer works from. Pure; time is not involved (see
 * makeAnchor / timeView).
 */
export function deriveModel(E, ids = {}) {
  const ok = (k) => isAvailable(strOf(E, k));
  const raw = {};
  for (const k of ENTITY_KEYS) raw[k] = strOf(E, k);

  // ---- B1: profile class --------------------------------------------------
  const b1 = ok('profile_state') ? strOf(E, 'profile_state') : null;
  let profile = 'unavailable';
  if (b1 !== null) {
    if (!KNOWN_CLASSES.has(b1)) profile = 'unrecognised';
    else if (UNUSABLE_CLASSES.has(b1)) profile = 'unusable';
    else if (b1 === 'VALID') profile = 'saved';
    else if (b1 === 'INVALIDATED') profile = 'invalidated';
    else profile = 'notsaved';
  }

  // ---- B2: summary --------------------------------------------------------
  const b2 = ok('summary') ? parseKv(strOf(E, 'summary'), KV_KEYS.summary) : null;
  const g = b2 && b2.g !== '-' ? parseU(b2.g) : null;
  const at = b2 && b2.at !== '-' ? parseU(b2.at) : null;
  const hw = b2 && b2.hw !== '-' ? parseU(b2.hw) : null;
  const idHex = b2 && /^[0-9A-F]{16}$/.test(b2.id) ? b2.id : null;

  // ---- B3: review ---------------------------------------------------------
  let b3 = null;
  let reviewReason = null;
  if (!ok('review')) reviewReason = 'absent';
  else {
    b3 = parseKv(strOf(E, 'review'), KV_KEYS.review);
    if (!b3) reviewReason = 'malformed';
  }
  const st = b3 ? b3.st : null;
  const stKnown = st !== null && KNOWN_ST.has(st);
  const hasCand = st === 'CANDIDATE_READY' || st === 'CANDIDATE_NOT_SAVEABLE';
  const exp = b3 && b3.exp !== '-' ? parseU(b3.exp, TTL_S) : null;
  const prior = b3 && KNOWN_CLASSES.has(b3.prior) ? b3.prior : null;
  const warn = b3 ? b3.warn : '-';
  const obl = b3 ? parseObl(b3.obl) : null;
  // 'none' = never evaluated (`-`), 'ok' = a well-formed six-entry vector, 'invalid' = present but not judgeable
  const oblState = !b3 || b3.obl === '-' ? 'none' : obl ? 'ok' : 'invalid';
  const latch = b3 ? parseLatch(b3.latch) : [];
  const sv = b3 ? parseSv(b3.sv) : { kind: 'none', codes: [], more: 0 };

  // ---- B9: last action-result --------------------------------------------
  const b9Avail = ok('last_result');
  const b9 = parseB9(b9Avail ? strOf(E, 'last_result') : '');

  // ---- review state (spec 4.3) -------------------------------------------
  let review;
  if (!b3) review = 'unavailable';
  else if (!stKnown) review = 'unrecognised';
  else if (st === 'READING') review = 'reading';
  else if (st === 'SAVING') review = 'saving';
  else if (st === 'CANDIDATE_READY') review = 'ready';
  else if (st === 'CANDIDATE_NOT_SAVEABLE') review = 'notsaveable';
  else if (b9.kind === 'refused') review = 'refused';
  else if (b9.kind === 'notcompleted') review = /changed during the read/.test(b9.raw) ? 'mismatch' : 'readerror';
  else if (b9.kind === 'expired') review = 'expired';
  else if (b9.kind === 'cleared') review = 'cleared';
  else if (b9.kind === 'internal') review = 'internal';
  else review = 'available';

  // ---- candidate / saved views -------------------------------------------
  const sl = ok('review_slots') ? parseSlotsEntity(strOf(E, 'review_slots'), false) : null;
  const cx = ok('review_context') ? parseContextEntity(strOf(E, 'review_context'), false) : null;
  const ssl = ok('saved_slots') ? parseSlotsEntity(strOf(E, 'saved_slots'), true) : null;
  const scx = ok('saved_context') ? parseContextEntity(strOf(E, 'saved_context'), true) : null;
  const candOK = !!(hasCand && sl && cx && sl.v === 'CAND' && cx.v === 'CAND');
  const savedOK = !!(ssl && scx && ssl.v === 'SAVED' && scx.v === 'SAVED');

  // ---- was the candidate compared with a TRUSTED stored profile? -----------------------------------------------
  // The firmware computes dx / dc / di only against a trusted stored profile (an authentic record whose effective
  // class is not UNREADABLE) and prints '-' otherwise; B7 / B8 are `v=NONE` in exactly that case. `cmp` is the ONE
  // place the card decides whether a comparison exists, and it is stricter than the strings: a class of UNREADABLE
  // (B1, or the candidate's prior class) is never comparable, even if masks were published next to it, so a diff
  // marker or a "matches" claim can never appear against a stored profile the firmware does not trust. Every
  // consumer of the masks (Live Match, the summary markers, the register table) reads cmp, never sl.dx / cx.dc / cx.di.
  const isMask = (h) => typeof h === 'string' && h !== '-' && parseHex(h) !== null;
  const untrusted = b1 === 'UNREADABLE' || prior === 'UNREADABLE';
  const comparable = candOK && !untrusted && isMask(sl.dx) && isMask(cx.dc);
  const cmp = {
    comparable,
    untrusted,
    dx: comparable ? sl.dx : '-',
    dc: comparable ? cx.dc : '-',
    di: comparable && isMask(cx.di) ? cx.di : '-',
  };

  // ---- base entities ------------------------------------------------------
  const onOff = (k) => (strOf(E, k) === 'on' ? true : strOf(E, k) === 'off' ? false : null);
  const supState = ok('supervision_state') ? strOf(E, 'supervision_state') : null;

  const reviewId = ok('review_id') && /^[0-9A-F]{16}$/.test(strOf(E, 'review_id')) ? strOf(E, 'review_id') : null;

  // ---- the arm switch and the three other write arms (optional entities) ------------------------------------
  // `configured` says whether the dashboard gave the card an arm entity at all; `state` is true / false / null (unavailable).
  const arm = { configured: !!(ids && ids.arm), state: onOff('arm') };
  const otherArms = {
    fp: onOff('free_power_arm'),
    dump: onOff('dump_arm'),
    manual: onOff('manual_arm'),
    configured: ['free_power_arm', 'dump_arm', 'manual_arm'].filter((k) => !!(ids && ids[k])).length,
  };
  // the last Save / Invalidate outcome (B9), checked against the profile class and generation the dongle publishes
  const savingAct = { family: 'save', outcome: 'progress', tone: 'neutral', detail: '', gen: null, newGen: null, witness: false, verified: false };
  const act = review === 'saving' ? savingAct : deriveAct(b9, b1, g, b2);

  // ---- blockers / notes ---------------------------------------------------
  // svBlockers: why the profile VALUES are not valid for Fallback V1 (check 2). blockers: every reason the
  // candidate cannot be saved (the candidate card): those plus the stored-profile class and a missing ID.
  // They are built for every candidate, so a READY candidate that carries an `sv=NO:` list, an unusable
  // prior class or no ID is shown as not saveable too (the firmware never emits that today).
  const priorBlocks = prior === 'UNREADABLE' || prior === 'SAVE_UNCONFIRMED';
  const svBlockers = [];
  const blockers = [];
  const notes = [];
  if (hasCand) {
    if (sv.kind === 'no') {
      const bctx = { reg244: sl ? sl.reg244 : null, reg243: cx ? cx.r243 : null, slots: sl ? sl.slots : [] };
      for (const code of sv.codes) svBlockers.push(blockerText(code, bctx));
      if (sv.more > 0) svBlockers.push(moreBlockers(sv.more));
    } else if (sv.kind !== 'ok') svBlockers.push(SV_UNCONFIRMED_BLOCKER);
    blockers.push(...svBlockers);
    if (priorBlocks) blockers.push(priorBlockerText(prior));
    else if (st === 'CANDIDATE_READY' && prior === null) blockers.push(PRIOR_UNKNOWN_BLOCKER);
    if (st === 'CANDIDATE_READY' && reviewId === null) blockers.push(NO_ID_BLOCKER);
    if (st === 'CANDIDATE_NOT_SAVEABLE' && blockers.length === 0) blockers.push(FALLBACK_BLOCKER);
  }
  if (st === 'CANDIDATE_READY' && prior === 'CORRUPT') notes.push(priorReplaceNote(prior));
  const warnings = warningRows(warn, sl ? sl.slots : []);

  // Eligible for a (future) save: the firmware says READY, the values are valid (sv=OK), the stored profile
  // class permits a save, and the candidate has a real ID. Expiry is applied on top by the renderers.
  const eligible = st === 'CANDIDATE_READY' && sv.kind === 'ok' && prior !== null && !priorBlocks && reviewId !== null;

  return {
    ids,
    raw,
    b1,
    profile,
    b2,
    g,
    at,
    hw,
    idHex,
    b3,
    reviewReason,
    st,
    stKnown,
    hasCand,
    exp,
    prior,
    warn,
    warnings,
    obl,
    oblState,
    latch,
    sv,
    b9,
    b9Avail,
    review,
    sl,
    cx,
    ssl,
    scx,
    candOK,
    savedOK,
    cmp,
    svBlockers,
    blockers,
    notes,
    eligible,
    reviewId,
    arm,
    otherArms,
    act,
    mismatch: review === 'mismatch' ? b9.mismatch : null,
    sup: { stable: onOff('supervision_stable'), state: supState },
    ntp: onOff('ntp_synced'),
    wl: onOff('write_lock'),
    online: onOff('configuration_online'),
    button: { available: strOf(E, 'review_button') !== undefined && strOf(E, 'review_button') !== 'unavailable' },
  };
}

/** Read the configured entities out of hass.states; `changed` holds each last_changed in ms (or null). */
export function readEntities(entities, hassStates) {
  const E = {};
  const changed = {};
  for (const k of ENTITY_KEYS) {
    const id = entities[k];
    const s = id && hassStates ? hassStates[id] : undefined;
    E[k] = s && s.state !== undefined && s.state !== null ? String(s.state) : undefined;
    const t = s && s.last_changed ? Date.parse(s.last_changed) : NaN;
    changed[k] = Number.isFinite(t) ? t : null;
  }
  return { E, changed };
}

// ---- countdown --------------------------------------------------------------
/**
 * The anchor is the firmware's `exp` plus the moment that value was
 * published (B3 last_changed, HA server time). When last_changed is missing
 * the receive time is used; an anchor in the future (browser clock behind the
 * server) is clamped to now so the countdown never runs backwards.
 */
export function makeAnchor({ exp, lastChangedMs, receivedMs, nowMs }) {
  if (!Number.isInteger(exp) || exp < 0 || exp > TTL_S) return null;
  let at = Number.isFinite(lastChangedMs) ? lastChangedMs : Number.isFinite(receivedMs) ? receivedMs : nowMs;
  if (at > nowMs) at = nowMs;
  return { exp, at };
}

/** Whole seconds left. Never rounded up; 0 means "expiring" (the firmware has not confirmed yet). */
export function remainingSeconds(anchor, nowMs) {
  if (!anchor) return null;
  const elapsed = Math.max(0, nowMs - anchor.at);
  const ms = anchor.exp * 1000 - elapsed;
  return ms <= 0 ? 0 : Math.floor(ms / 1000);
}

/**
 * Candidate age in whole seconds: time since the publish plus what the
 * firmware had already consumed (120 - exp). The elapsed part is rounded UP
 * so that age + remaining always adds up to exactly 2:00 on screen (the
 * remaining time is rounded down).
 */
export function ageSeconds(anchor, nowMs) {
  if (!anchor) return null;
  return Math.ceil(Math.max(0, nowMs - anchor.at) / 1000) + (TTL_S - anchor.exp);
}

export function countdownBucket(rem) {
  if (rem === null || rem === undefined) return null;
  if (rem > SOON_S) return 'plenty';
  if (rem >= URGENT_S) return 'soon';
  if (rem >= 1) return 'urgent';
  return 'zero';
}

/**
 * The arm's own countdown: the anchor is the moment Home Assistant last changed the arm switch to on, plus the
 * firmware's 120 s limit. The firmware applies the limit on its 10 s tick, so the arm can stay on for up to about
 * 10 s after this reaches zero: the card then says "expiring" and offers no confirm, it never declares the arm off.
 */
export function armView(anchor, nowMs) {
  if (!anchor) return { has: false, rem: null, bucket: null };
  const rem = remainingSeconds(anchor, nowMs);
  return { has: true, rem, bucket: countdownBucket(rem) };
}

export function timeView(anchor, nowMs, armAnchor = null) {
  const arm = armView(armAnchor, nowMs);
  if (!anchor) return { has: false, rem: null, bucket: null, age: null, createdMs: null, pct: 0, arm };
  const rem = remainingSeconds(anchor, nowMs);
  return {
    has: true,
    rem,
    bucket: countdownBucket(rem),
    age: ageSeconds(anchor, nowMs),
    createdMs: anchor.at - (TTL_S - anchor.exp) * 1000,
    pct: Math.max(0, Math.min(100, (rem / TTL_S) * 100)),
    arm,
  };
}

/** Texts that fill the `data-t` placeholders (the only per-second DOM writes). */
export function timeTexts(tv) {
  const a = tv.arm || { rem: null };
  return {
    rem: tv.rem === null ? '—' : tv.rem === 0 ? 'expiring…' : mmss(tv.rem),
    age: tv.age === null ? '—' : mmss(tv.age),
    arm: a.rem === null ? '—' : a.rem === 0 ? 'expiring…' : mmss(a.rem),
  };
}

// ===========================================================================
// 5. register table, checks, review button state
// ===========================================================================
function groupRegs() {
  const rows = [{ reg: 244, name: 'Export mode', cls: 'E1' }];
  for (let i = 0; i < 6; i++) rows.push({ reg: 256 + i, name: `Slot ${i + 1} power`, cls: 'E1' });
  for (let i = 0; i < 6; i++) rows.push({ reg: 268 + i, name: `Slot ${i + 1} target SOC`, cls: 'E1' });
  for (let i = 0; i < 6; i++) rows.push({ reg: 274 + i, name: `Slot ${i + 1} source / mode`, cls: 'E1' });
  rows.push({ reg: 232, name: 'Grid charge master', cls: 'CTX' });
  rows.push({ reg: 243, name: 'Energy management model', cls: 'CTX' });
  rows.push({ reg: 248, name: 'TOU master', cls: 'CTX' });
  for (let i = 0; i < 6; i++) rows.push({ reg: 250 + i, name: `Slot ${i + 1} start`, cls: 'CTX' });
  rows.push({ reg: 230, name: 'Grid-charge current', cls: 'INFO' });
  rows.push({ reg: 245, name: 'Export limit', cls: 'INFO' });
  rows.push({ reg: 247, name: 'Solar export flag', cls: 'INFO' });
  return rows.map((r) => Object.freeze(r));
}
/** The 31 Fallback Profile registers in the FB-A struct order. */
export const REGS = Object.freeze(groupRegs());
export const CLASS_TIP = Object.freeze({
  E1: 'restored by Fallback V1',
  CTX: 'compared, never written',
  INFO: 'recorded only',
});

/** Register -> numeric value from a parsed slots/context pair. */
export function wordsFrom(sl, cx) {
  const w = {};
  if (sl) {
    if (sl.reg244 !== null && sl.reg244 !== undefined) w[244] = sl.reg244;
    sl.slots.forEach((s, i) => {
      if (!s) return;
      w[256 + i] = s.w;
      w[268 + i] = s.soc;
      w[274 + i] = s.src;
      w[250 + i] = s.hhmm;
    });
  }
  if (cx) {
    const put = (reg, v) => {
      if (v !== null && v !== undefined) w[reg] = v;
    };
    put(232, cx.r232);
    put(243, cx.r243);
    put(248, cx.r248);
    put(230, cx.r230);
    put(245, cx.r245);
    put(247, cx.r247);
  }
  return w;
}

/** Human decode of one register word (raw table "Decoded" column). */
export function decodeWord(reg, val) {
  if (val === undefined || val === null) return '';
  if (reg === 244) return dec244(val);
  if (reg === 243) return dec243(val);
  if (reg >= 274 && reg <= 279) {
    const d = decSrc(val);
    return `${d.src} / ${modeText(d)}`;
  }
  if (reg >= 250 && reg <= 255) return hhmmText(val);
  if (reg >= 256 && reg <= 261) return `${val} W`;
  if (reg >= 268 && reg <= 273) return `${val} %`;
  if (reg === 232) return `grid charging ${bit0(val) ? 'on' : 'off'}`;
  if (reg === 248) return `TOU schedule ${bit0(val) ? 'on' : 'off'}`;
  if (reg === 247) return `solar export ${bit0(val) ? 'on' : 'off'}`;
  if (reg === 230) return `${val} A`;
  return String(val);
}

/**
 * The 31-row raw table with the pass-column rule of design 5.7. The
 * firmware publishes one set of words, and only when pass 1 and pass 2
 * agreed, so per-pass values are never invented:
 *   candidate present -> pass 1 = pass 2 = the published word, match ok
 *   pass mismatch     -> only the register named by the firmware has values
 *   any other state   -> both pass columns empty
 */
export function buildRegisterTable(vm) {
  const hasWords = vm.candOK;
  const cw = hasWords ? wordsFrom(vm.sl, vm.cx) : {};
  const sw = vm.savedOK ? wordsFrom(vm.ssl, vm.scx) : {};
  const mm = !hasWords ? vm.mismatch : null;
  const rows = REGS.map(({ reg, name, cls }) => {
    let p1 = '—';
    let p2 = '—';
    let match = 'none';
    if (hasWords) {
      p1 = p2 = formatWord(reg, cw[reg]);
      match = cw[reg] === undefined ? 'none' : 'ok';
    } else if (mm && mm.reg === reg) {
      p1 = mm.a;
      p2 = mm.b;
      match = 'bad';
    }
    let delta = 'none';
    if (hasWords && vm.savedOK && vm.cmp.comparable) {
      const d = regDiffAny(reg, vm.cmp.dx, vm.cmp.dc, vm.cmp.di);
      delta = d === null ? 'none' : d ? 'ne' : 'eq';
    }
    const shown = hasWords ? cw[reg] : sw[reg];
    return {
      reg,
      name,
      cls,
      p1,
      p2,
      match,
      saved: formatWord(reg, sw[reg]),
      delta,
      decoded: decodeWord(reg, shown),
    };
  });
  let caption = 'No review values to show.';
  if (hasWords) {
    caption = 'Pass 1 and pass 2 agreed on all 31 registers; the firmware publishes the agreed words once.';
    const note = notComparedNote(vm);
    if (note) caption += ` ${note}`;
  } else if (mm) caption = 'The firmware reports the first differing register only.';
  return {
    rows,
    caption,
    mode: hasWords ? 'candidate' : mm ? 'mismatch' : 'none',
    savedLabel: vm.savedOK && vm.ssl.g !== null ? `Saved g${vm.ssl.g}` : 'Saved',
  };
}

/**
 * The six save-readiness checks. Checks 5 and 6 are SAVE prerequisites only:
 * the Review button never depends on them. Check 4 is evaluated at Review.
 */
export function buildChecks(vm, tv) {
  const checks = [];
  const add = (state, label, detail, tip = '') => checks.push({ n: checks.length + 1, state, label, detail, tip });
  const L1 = 'Both read passes identical';
  const L2 = 'Profile values valid for Fallback V1';
  const L3 = 'Candidate not expired';
  const L4 = 'No temporary operation active';
  const L5 = 'Supervision stable';
  const L6 = 'Trusted time';
  if (vm.review === 'unavailable' || vm.review === 'unrecognised') {
    [L1, L2, L3, L4, L5, L6].forEach((l) => add('unknown', l, 'Entities unavailable'));
    return checks;
  }
  // 1
  if (vm.review === 'reading') add('pending', L1, 'Reading now');
  else if (vm.review === 'saving') add('pending', L1, 'Re-reading before the commit');
  else if (vm.hasCand) add('pass', L1, '31 / 31 registers agree');
  else if (vm.mismatch) add('fail', L1, `register ${vm.mismatch.reg}: ${vm.mismatch.a} then ${vm.mismatch.b}`);
  else if (vm.review === 'readerror' || vm.review === 'internal') add('unknown', L1, 'Read not completed');
  else if (vm.review === 'refused') add('unknown', L1, 'Not read (review refused)');
  else add('unknown', L1, 'Not reviewed yet');
  // 2: the firmware's sv verdict decides, whatever the candidate state says (a READY candidate that carries
  // `sv=NO:` does not pass this check, and shows the same sv-code texts as a not-saveable one)
  if (vm.hasCand) {
    if (vm.sv.kind !== 'ok') add('fail', L2, vm.svBlockers[0]);
    else if (vm.warnings.length) {
      add('warn', L2, `${vm.warnings.length} warning${vm.warnings.length === 1 ? '' : 's'} - see candidate`);
    } else add('pass', L2, 'All 31 values within the V1 domain');
  } else add('unknown', L2, 'Not reviewed yet');
  // 3: one countdown rule everywhere (countdownBucket): more than 45 s left passes, 45 s and below warns
  // ("expiring soon"), zero is waiting for the firmware (never declared expired by the card)
  if (vm.hasCand && tv.has) {
    if (tv.bucket === 'zero') add('fail', L3, EXPIRING_TEXT);
    else if (tv.bucket === 'plenty') add('pass', L3, '@rem@ left');
    else add('warn', L3, '@rem@ left - expiring soon');
  } else if (vm.hasCand) add('unknown', L3, 'Time left not known');
  else if (vm.review === 'expired') add('fail', L3, 'Expired');
  else add('unknown', L3, 'Not reviewed yet');
  // 4: the obligation vector is a snapshot taken by the Review gate and the firmware keeps publishing it
  // unchanged afterwards. It is only judged where it is that gate's current outcome: while a candidate
  // exists, while reading, and on a refusal. In idle, expired and cleared states it is NOT live, so it is
  // never shown as a pass (a stale "clear" must not contradict "candidate cleared").
  const oblFresh = vm.hasCand || vm.review === 'reading' || vm.review === 'refused';
  const oblName = (e) => own(DOMAIN_LABEL, e.d) || e.d;
  const oblKind = (e) => own(KIND_TEXT, e.k) || e.k;
  if (oblFresh && vm.obl) {
    const nonClear = vm.obl.filter((e) => oblKindClass(e.k) !== 'clear');
    const lock = nonClear.some((e) => oblKindClass(e.k) === 'lockout');
    const shown = nonClear.slice(0, 3).map((e) => `${oblName(e)} ${oblKind(e)}`);
    const tip = vm.obl.map((e) => `${oblName(e)}: ${e.k} (${oblKind(e)})`).join('; ');
    if (nonClear.length === 0) add('pass', L4, 'Free Power, Dump to Grid, register 244 test: clear at Review', tip);
    else add(lock ? 'fail' : 'warn', L4, shown.join('; '), tip);
  } else if (vm.review === 'cleared') {
    add('warn', L4, vm.b9.detail || 'A temporary operation started after the review');
  } else if (vm.oblState === 'invalid') {
    add('unknown', L4, 'Obligation vector not recognised (see technical detail)');
  } else if (vm.obl && !oblFresh) {
    add('unknown', L4, 'Last checked at Review (not live)', `At the last review: ${vm.obl.map((e) => `${oblName(e)} ${e.k}`).join('; ')}`);
  } else add('unknown', L4, 'Checked at Review');
  // 5: the firmware requires BOTH state SUPERVISED and a stable run of beats ("SUPERVISED alone is insufficient")
  // FB-B2 (CARD-01): a state that IS shown and is not SUPERVISED fails whatever the stable entity says (it may be unavailable);
  // "unknown" is only for what the card cannot judge at all
  if (vm.sup.stable === null && vm.sup.state !== null && vm.sup.state !== 'SUPERVISED') add('fail', L5, supervisionStateText(vm.sup.state));
  else if (vm.sup.stable === null) add('unknown', L5, 'Entity unavailable');
  else if (vm.sup.stable && vm.sup.state === 'SUPERVISED') add('pass', L5, 'Home Assistant heartbeat stable');
  else if (vm.sup.stable && vm.sup.state === null) add('unknown', L5, 'Stable, but the supervision state is not shown');
  else if (vm.sup.stable) add('fail', L5, supervisionStateText(vm.sup.state));
  else if (vm.sup.state === 'SUPERVISED') add('warn', L5, 'Recovering - waiting for a stable run of beats');
  else add('fail', L5, `No stable heartbeat (${vm.sup.state || 'state unknown'})`);
  // 6
  if (vm.ntp === null) add('unknown', L6, 'Entity unavailable');
  else if (vm.ntp) add('pass', L6, 'Clock NTP-synchronised this boot');
  else add('fail', L6, 'Not NTP-synchronised this boot; a save would be refused');
  return checks;
}

/** One short clause saying why a candidate that passed the value checks is still not eligible for a save. */
export function ineligibleReason(vm) {
  if (vm.prior === 'UNREADABLE' || vm.prior === 'SAVE_UNCONFIRMED') return `the stored profile is ${vm.prior}`;
  if (vm.sv.kind !== 'ok') return 'the firmware did not confirm the profile values';
  if (vm.st === 'CANDIDATE_READY' && vm.reviewId === null) return 'the candidate has no valid ID';
  if (vm.st === 'CANDIDATE_READY' && vm.prior === null) return 'the stored profile class is not recognised';
  return 'the firmware reports this candidate as not saveable';
}

/**
 * Review button: disabled (still focusable, with a reason) per design 5.3. `act` is the kind of Save / Invalidate
 * request this card has sent and not yet seen answered ('save' | 'invalidate' | null).
 */
export function reviewButtonState(vm, { pending = false, act = null } = {}) {
  if (vm.review === 'unavailable') return { disabled: true, why: 'Entities unavailable' };
  if (vm.review === 'unrecognised') return { disabled: true, why: 'Review status not recognised' };
  if (vm.review === 'reading') return { disabled: true, why: 'Review in progress' };
  if (vm.review === 'saving' || act === 'save') return { disabled: true, why: 'Save in progress' };
  if (act === 'invalidate') return { disabled: true, why: 'Invalidate in progress' };
  if (vm.wl === true) return { disabled: true, why: 'Inverter bus busy - try again shortly' };
  if (!vm.button.available) return { disabled: true, why: 'Review button unavailable' };
  if (pending) return { disabled: true, why: 'Review requested' };
  return { disabled: false, why: '' };
}

/**
 * One caption for a candidate that was NOT compared with the stored profile, or '' when it was (or there is no candidate,
 * or there is simply no stored profile to talk about). Said in card 6 under the candidate values and in the register table
 * caption, so the missing difference markers are explained instead of looking like "no differences".
 */
export function notComparedNote(vm) {
  if (!vm.candOK || vm.cmp.comparable) return '';
  if (vm.cmp.untrusted || vm.profile === 'unusable') {
    const cls = vm.profile === 'unusable' ? vm.b1 : 'UNREADABLE';
    return `Not compared: the stored profile is ${cls} and cannot be trusted, so no difference markers are shown.`;
  }
  if (vm.profile === 'saved') return 'Not compared: the firmware reported no comparison with the saved profile, so no difference markers are shown.';
  return '';
}

/** The disabled "Saved profile" source button: its short label and tooltip when there is no saved view to show. */
export function savedSegmentNote(vm) {
  if (vm.profile === 'unusable' && vm.b1 !== 'PROFILE_LOST') {
    return { sub: 'not trusted', tip: `The stored profile is ${vm.b1} and is not trusted: no saved values are shown.` };
  }
  return { sub: 'no saved profile', tip: 'no saved profile' };
}

/** Live Match derived from the most recent review only (spec 4.3 / 5.2). */
export function liveMatch(vm, tv) {
  const names = [];
  if (vm.candOK && vm.savedOK === true && vm.cmp.comparable) {
    // chip names come from dx/dc only (information-only registers are not "settings")
    for (const { reg, name } of REGS) {
      const { core } = regDiff(reg, vm.cmp.dx, vm.cmp.dc, vm.cmp.di);
      if (core === true) names.push(name);
    }
  }
  const base = { names, chips: names.slice(0, 3), more: Math.max(0, names.length - 3), icon: 'help' };
  if (vm.review === 'unavailable' || vm.review === 'unrecognised' || vm.b1 === null) {
    return { ...base, word: 'NOT REPORTING', tone: 'idle', sentence: [SENTENCE.entitiesUnavailable], basis: 'none' };
  }
  if (vm.profile !== 'saved') {
    // an unusable stored profile is named (and, for UNREADABLE, said to be untrusted); no profile at all, or an
    // invalidated one, keeps the plain "no saved profile" sentence
    const sentence = vm.profile === 'unusable' ? untrustedSentence(vm.b1) : SENTENCE.noSavedToCompare;
    return { ...base, word: 'UNKNOWN', tone: 'idle', sentence: [sentence], basis: 'none' };
  }
  if (vm.review === 'reading' || vm.review === 'saving') {
    const sentence = vm.review === 'saving' ? 'Re-reading the inverter before saving.' : 'Reading the inverter now.';
    return { ...base, word: 'CHECKING', tone: 'busy', icon: 'clock', sentence: [sentence], basis: 'none' };
  }
  if (vm.candOK) {
    // vm.cmp is '-' for every mask unless the candidate was compared with a TRUSTED stored profile (see deriveModel)
    if (!vm.cmp.comparable) {
      return { ...base, word: 'UNKNOWN', tone: 'idle', sentence: [SENTENCE.notComparable], basis: 'review' };
    }
    const dx = vm.cmp.dx;
    const nc = popcount(vm.cmp.dc, DC_BITS);
    const nx = popcount(dx, DX_BITS);
    const places = (n) => `${n} place${n === 1 ? '' : 's'}`;
    if (nc) {
      // the headline says a context value differs; the count covers every differing register (dc and dx),
      // the same set the chips below it name
      return {
        ...base,
        word: 'DIFFERS (CONTEXT)',
        tone: 'warn',
        icon: 'alert',
        sentence: [`Slot times or context differ from the saved profile in ${places(nc + nx)} (as of the review `, 'age', ' ago).'],
        basis: 'review',
      };
    }
    if (nx) {
      return {
        ...base,
        word: 'DIFFERS',
        tone: 'warn',
        icon: 'alert',
        sentence: [`Live settings differ from the saved profile in ${places(nx)} (as of the review `, 'age', ' ago).'],
        basis: 'review',
      };
    }
    // The headline is about the settings and the context (dx + dc). The sentence must not claim more than the firmware
    // published: "31 of 31 registers matched" is only true when the information-only mask di is zero too. With a
    // non-zero di (230 / 245 / 247, or the upper bits of 232 / 248) the headline stays and the sentence says what
    // matched and what did not; with no di at all it does not claim the information-only registers either way.
    const infoKnown = vm.cmp.di !== '-';
    const infoDiff = infoKnown && popcount(vm.cmp.di, DI_BITS) > 0;
    let sentence;
    if (infoDiff) {
      sentence = ['All compared settings and context matched at the review ', 'age', ' ago. Info-only values differ (not restored by Fallback V1).'];
    } else if (infoKnown) sentence = ['31 of 31 registers matched at the review ', 'age', ' ago.'];
    else sentence = ['All compared settings and context matched at the review ', 'age', ' ago. Info-only values were not compared.'];
    return {
      ...base,
      word: 'MATCHES SAVED PROFILE',
      tone: 'ok',
      icon: 'check',
      sentence,
      basis: 'review',
    };
  }
  return { ...base, word: 'UNKNOWN', tone: 'idle', sentence: [SENTENCE.pressReview], basis: 'none' };
}

// ===========================================================================
// 5b. guarded Save / Invalidate: effect, gates and request state (all pure)
// ===========================================================================
// The firmware's own gate is the authority (arm, ID, phrase, time limits, one-shot). Everything below only lets the
// card refuse early, with the firmware's wording, so that an operator does not spend a one-shot arm and a candidate
// on a request that is certain to be refused. An item the card cannot judge (an optional entity that is not
// configured) is 'unknown' and does not block: the dongle checks it when you save.

/** 16 hex digits in groups of four, as the candidate ID is shown. */
export const groupId = (id) => (typeof id === 'string' && HEX16_RE.test(id) ? id.match(/.{4}/g).join(' ') : '—');

export const GATE_LABEL = Object.freeze({
  arm: 'Arm on',
  flow: 'No other Fallback Profile operation running',
  candidate: 'Candidate reviewed and saveable',
  fresh: 'Candidate not expired',
  stored: 'Stored profile can be replaced',
  heartbeat: 'Home Assistant heartbeat stable',
  ntp: 'Trusted time',
  arms: 'No other write arm on',
  bus: 'Inverter bus idle',
  obligations: 'No temporary operation active',
  profile: 'Saved profile is VALID',
  generation: 'Generation can advance',
  binding: 'Profile ID matches the saved values',
});

/**
 * What a save of the current candidate will do to the stored profile, in the firmware's generation arithmetic
 * (the base is the larger of the stored generation and the generation record, plus one). `gen` is EXPECTED: the dongle
 * also keeps a RAM-only high-water mark that no entity publishes, and confirms the final number after the save.
 */
const GEN_PRIORS = new Set(['VALID', 'INVALIDATED', 'CORRUPT_DOMAIN', 'PROFILE_STALE']);
/**
 * FB-B2 (CARD-07): the generation a save is expected to write, or null when it cannot be derived from what the dashboard shows.
 * The base is the larger of the stored generation and the generation record; a missing summary (B2), a stored generation that
 * the profile class says exists but B2 does not carry, or an unrecognised class all mean "not known", never "generation 1".
 */
export function expectedGeneration(vm) {
  if (vm.b2 === null || vm.prior === null) return null;
  if (GEN_PRIORS.has(vm.prior) && vm.g === null) return null;
  if (vm.prior === 'PROFILE_LOST' && vm.hw === null) return null;
  return Math.max(vm.g === null ? 0 : vm.g, vm.hw === null ? 0 : vm.hw) + 1;
}

export function saveEffect(vm) {
  const gen = expectedGeneration(vm);
  const result = gen === null ? FLOW_TEXT.generationUnknown : `Expected result: generation ${gen}.`;
  const named = {
    VALID: 'the saved profile',
    INVALIDATED: 'the invalidated profile',
    CORRUPT_DOMAIN: 'a stored profile whose values are out of range',
    PROFILE_STALE: 'a stored profile that is out of step',
  };
  const out = { kind: null, gen, replaces: null, sentence: '' };
  switch (vm.prior) {
    case 'NOT_CAPTURED':
      out.kind = 'first';
      out.sentence = `First save: no profile is stored yet. ${result}`;
      break;
    case 'CORRUPT':
      out.kind = 'replace_corrupt';
      out.sentence = `Replaces a damaged stored profile. ${result}`;
      break;
    case 'PROFILE_LOST':
      out.kind = 'replace_lost';
      out.sentence = `The stored profile is missing${vm.hw === null ? '' : ` (last known generation ${vm.hw})`}. A new one replaces it. ${result}`;
      break;
    case 'VALID':
    case 'INVALIDATED':
    case 'CORRUPT_DOMAIN':
    case 'PROFILE_STALE':
      out.kind = 'replace';
      out.replaces = vm.g === null ? null : { cls: vm.prior, gen: vm.g };
      out.sentence = `Replaces ${named[vm.prior]}${vm.g === null ? '' : ` (generation ${vm.g})`}. ${result}`;
      break;
    default:
  }
  return out;
}

const gateItem = (id, state, label, detail, required = false) => ({ id, state, label, detail, required });
/** A failing item, or an unknown one that the card cannot do without, stops the request. */
export const itemBlocks = (it) => it.state === 'fail' || (it.state === 'unknown' && it.required);

/** The "Arm on" item shared by both gates. `@arm@` is the live arm countdown placeholder. */
function armItem(vm, tv, notSetUp, cancelling = false) {
  const L = GATE_LABEL.arm;
  if (!vm.arm.configured) return gateItem('arm', 'fail', L, notSetUp, true);
  if (vm.arm.state === null) return gateItem('arm', 'unknown', L, FLOW_TEXT.armUnavailable, true);
  if (!vm.arm.state) return gateItem('arm', 'fail', L, FLOW_TEXT.armNotOn, true);
  if (cancelling) return gateItem('arm', 'fail', L, FLOW_TEXT.armCancelling, true);
  const a = tv && tv.arm;
  if (a && a.has && a.bucket === 'zero') return gateItem('arm', 'fail', L, FLOW_TEXT.armExpiring, true);
  return gateItem('arm', 'pass', L, a && a.has ? '@arm@ left' : 'On', true);
}

function flowItem(vm, pending) {
  const L = GATE_LABEL.flow;
  if (pending || vm.review === 'reading' || vm.review === 'saving') return gateItem('flow', 'fail', L, FLOW_TEXT.inFlight, true);
  if (vm.review === 'unavailable' || vm.review === 'unrecognised') return gateItem('flow', 'unknown', L, 'The review status is not available', true);
  return gateItem('flow', 'pass', L, 'None running', true);
}

function busItem(vm) {
  const L = GATE_LABEL.bus;
  if (vm.wl === null) return gateItem('bus', 'unknown', L, FLOW_TEXT.checkedAtSave);
  if (vm.wl) return gateItem('bus', 'fail', L, FLOW_TEXT.busBusy);
  return gateItem('bus', 'pass', L, 'Free');
}

function gateVerdict(items) {
  const blocking = items.filter(itemBlocks);
  const other = blocking.filter((i) => i.id !== 'arm');
  return {
    allowed: blocking.length === 0,
    allowedToArm: other.length === 0,
    why: blocking.length ? blocking[0].detail : '',
    whyToArm: other.length ? other[0].detail : '',
  };
}

/**
 * Save gate (firmware gates G1-G16, as far as the entities show them). `tv` carries the candidate and arm countdowns,
 * `ctx.pending` says a request of this card is still unanswered.
 * Returns {allowed, allowedToArm, why, whyToArm, variant, id, phrase, effect, items}: `allowedToArm` is true when
 * everything except the arm itself passes (the Arm Save button's condition), `allowed` when the arm is on as well.
 */
export function saveGate(vm, tv, ctx = {}) {
  const L = GATE_LABEL;
  const T = FLOW_TEXT;
  const items = [armItem(vm, tv, T.notSetUp, !!ctx.cancelling), flowItem(vm, !!ctx.pending)];
  // G3 candidate
  if (vm.review === 'notsaveable') items.push(gateItem('candidate', 'fail', L.candidate, 'This candidate is not saveable: see the reasons above', true));
  else if (vm.st !== 'CANDIDATE_READY') items.push(gateItem('candidate', 'fail', L.candidate, T.noCandidate, true));
  else if (vm.sv.kind !== 'ok') items.push(gateItem('candidate', 'fail', L.candidate, vm.svBlockers[0] || SV_UNCONFIRMED_BLOCKER, true));
  else if (vm.reviewId === null) items.push(gateItem('candidate', 'fail', L.candidate, NO_ID_BLOCKER, true));
  // FB-B2 (CARD-07): the values the operator is asked to confirm must be on screen (B5 and B6 parsed as a candidate)
  else if (!vm.candOK) items.push(gateItem('candidate', 'unknown', L.candidate, T.candValuesMissing, true));
  else items.push(gateItem('candidate', 'pass', L.candidate, 'Both passes agreed on all 31 registers', true));
  // G4 candidate age
  if (vm.st !== 'CANDIDATE_READY') items.push(gateItem('fresh', 'unknown', L.fresh, 'Not reviewed yet', true));
  else if (!tv || !tv.has) items.push(gateItem('fresh', 'unknown', L.fresh, 'Time left not known', true));
  else if (tv.bucket === 'zero') items.push(gateItem('fresh', 'fail', L.fresh, T.candidateExpiring, true));
  else items.push(gateItem('fresh', 'pass', L.fresh, '@rem@ left', true));
  // G9 / G9a stored profile class
  const p = vm.prior;
  if (vm.st !== 'CANDIDATE_READY' && vm.st !== 'CANDIDATE_NOT_SAVEABLE') items.push(gateItem('stored', 'unknown', L.stored, 'Not reviewed yet', true));
  else if (p === null) items.push(gateItem('stored', 'unknown', L.stored, PRIOR_UNKNOWN_BLOCKER, true));
  else if (p === 'UNREADABLE' || p === 'SAVE_UNCONFIRMED') items.push(gateItem('stored', 'fail', L.stored, priorBlockerText(p), true));
  // FB-B2 (CARD-07): the saved-profile summary (B2) is what the "Expected generation" and "Stored now" rows are derived from
  else if (expectedGeneration(vm) === null) items.push(gateItem('stored', 'unknown', L.stored, T.summaryMissing, true));
  else items.push(gateItem('stored', 'pass', L.stored, p === 'CORRUPT' ? 'Damaged: saving replaces it (REPLACE CORRUPT confirmation)' : `Stored profile: ${p}`, true));
  // G10 heartbeat (state SUPERVISED and a stable run of beats)
  const { stable, state } = vm.sup;
  // FB-B2 (CARD-01): a state that is shown and is not SUPERVISED fails whatever the stable entity says (it may be unavailable)
  if (stable === null && state !== null && state !== 'SUPERVISED') items.push(gateItem('heartbeat', 'fail', L.heartbeat, supervisionStateText(state)));
  else if (stable === null) items.push(gateItem('heartbeat', 'unknown', L.heartbeat, T.checkedAtSave));
  else if (stable && state === 'SUPERVISED') items.push(gateItem('heartbeat', 'pass', L.heartbeat, 'Stable'));
  else if (stable && state === null) items.push(gateItem('heartbeat', 'unknown', L.heartbeat, T.checkedAtSave));
  else if (stable) items.push(gateItem('heartbeat', 'fail', L.heartbeat, supervisionStateText(state)));
  else items.push(gateItem('heartbeat', 'fail', L.heartbeat, T.heartbeat));
  // G11 trusted time
  if (vm.ntp === null) items.push(gateItem('ntp', 'unknown', L.ntp, T.checkedAtSave));
  else if (vm.ntp) items.push(gateItem('ntp', 'pass', L.ntp, 'Clock NTP-synchronised this boot'));
  else items.push(gateItem('ntp', 'fail', L.ntp, T.ntp));
  // G12 the three other write arms
  const arms = [
    ['Free Power', vm.otherArms.fp],
    ['Dump to Grid', vm.otherArms.dump],
    ['Manual configuration', vm.otherArms.manual],
  ];
  const on = arms.filter(([, v]) => v === true).map(([n]) => n);
  if (on.length) items.push(gateItem('arms', 'fail', L.arms, `${FLOW_TEXT.armsOn} (on now: ${on.join(', ')})`));
  else if (arms.every(([, v]) => v === false)) items.push(gateItem('arms', 'pass', L.arms, 'Free Power, Dump to Grid and Manual configuration arms are off'));
  else items.push(gateItem('arms', 'unknown', L.arms, T.checkedAtSave));
  // G14 bus
  items.push(busItem(vm));
  // G15 / G16 temporary operations, as of the review
  if (vm.st !== 'CANDIDATE_READY' && vm.st !== 'CANDIDATE_NOT_SAVEABLE') items.push(gateItem('obligations', 'unknown', L.obligations, 'Not reviewed yet'));
  else if (vm.obl) {
    const nonClear = vm.obl.filter((e) => oblKindClass(e.k) !== 'clear');
    if (nonClear.length) {
      const shown = nonClear.slice(0, 3).map((e) => `${own(DOMAIN_LABEL, e.d) || e.d} ${own(KIND_TEXT, e.k) || e.k}`);
      items.push(gateItem('obligations', 'fail', L.obligations, shown.join('; ')));
    } else items.push(gateItem('obligations', 'pass', L.obligations, 'Clear at Review; the dongle checks again when you save'));
  } else items.push(gateItem('obligations', 'unknown', L.obligations, 'Obligation vector not recognised'));

  const replaceCorrupt = vm.prior === 'CORRUPT';
  return {
    ...gateVerdict(items),
    variant: replaceCorrupt ? 'replace_corrupt' : 'save',
    id: vm.reviewId,
    phrase: vm.reviewId ? phraseFor('SAVE', vm.reviewId, replaceCorrupt) : '',
    effect: vm.hasCand ? saveEffect(vm) : null,
    items,
  };
}

/**
 * Invalidate gate (ARCH 4.8): a VALID profile, no operation in flight, a bus that is not busy, a generation that can
 * advance, and the arm. NOT required: a stable heartbeat, trusted time, clear obligations, the other arms, or a candidate.
 */
export function invalidateGate(vm, tv, ctx = {}) {
  const L = GATE_LABEL;
  const T = FLOW_TEXT;
  const items = [armItem(vm, tv, T.invalidateNotSetUp, !!ctx.cancelling), flowItem(vm, !!ctx.pending)];
  const valid = vm.profile === 'saved' && vm.idHex !== null && vm.g !== null;
  if (valid) items.push(gateItem('profile', 'pass', L.profile, `Generation ${vm.g}`, true));
  else if (vm.profile === 'saved') items.push(gateItem('profile', 'fail', L.profile, 'The saved profile ID is not available yet', true));
  else items.push(gateItem('profile', 'fail', L.profile, `profile is ${vm.b1 || 'not reported'}; only a VALID profile can be invalidated`, true));
  if (!valid) items.push(gateItem('generation', 'unknown', L.generation, 'No saved profile', true));
  else if (vm.g >= U32_MAX) items.push(gateItem('generation', 'fail', L.generation, 'generation counter exhausted', true));
  else items.push(gateItem('generation', 'pass', L.generation, 'Below the counter limit', true));
  if (!valid) items.push(gateItem('binding', 'unknown', L.binding, 'No saved profile', true));
  else if (vm.savedOK && vm.ssl && vm.ssl.b === vm.idHex.slice(0, 8)) items.push(gateItem('binding', 'pass', L.binding, 'The saved values and the record ID agree', true));
  else items.push(gateItem('binding', 'fail', L.binding, 'The saved values on screen do not match the stored profile ID; wait for the dashboard to update', true));
  items.push(busItem(vm));
  return {
    ...gateVerdict(items),
    id: vm.idHex,
    phrase: vm.idHex ? phraseFor('INVALIDATE', vm.idHex) : '',
    discardsCandidate: vm.hasCand,
    items,
  };
}

/** The Arm Save / Arm Invalidate button: enabled only when everything except the arm passes and the arm is off. */
export function armButtonState(gate, vm, { pending = false, kind = 'save', cancelling = false } = {}) {
  if (!vm.arm.configured) return { disabled: true, why: kind === 'invalidate' ? FLOW_TEXT.invalidateNotSetUp : FLOW_TEXT.notSetUp };
  if (pending) return { disabled: true, why: FLOW_TEXT.armRequested };
  if (vm.arm.state === null) return { disabled: true, why: FLOW_TEXT.armUnavailable };
  if (vm.arm.state === true) return { disabled: true, why: cancelling ? FLOW_TEXT.armCancelling : FLOW_TEXT.armAlreadyOn };
  if (!gate.allowedToArm) return { disabled: true, why: gate.whyToArm };
  return { disabled: false, why: '' };
}

/** The request a click has sent. `keys` are the entity change keys at send time; `effect` is saveEffect() for a save. */
export function makeFlow(kind, { id, variant = 'save', effect = null, vm, nowMs, keys }) {
  return {
    kind,
    state: 'sent',
    id,
    variant,
    gen: effect ? effect.gen : null,
    effectKind: effect ? effect.kind : null,
    replaces: effect ? effect.replaces : null,
    atMs: nowMs,
    review0: vm.review,
    b9Key: keys.b9,
    armOn: vm.arm.state === true,
  };
}

/** 'save' | 'invalidate' while a request is on its way or running, else null. */
export const flowPendingKind = (flow) => (flow && (flow.state === 'sent' || flow.state === 'running') ? flow.kind : null);

/**
 * One step of the request state. 'sent' becomes 'running' when the dongle reports SAVING, and ends (null) when the
 * dongle answered: the review state changed from what it was at send time (B3 left CANDIDATE_READY) or the last-action text
 * changed. FB-B2 (CARD-05): the arm turning off is NOT an answer by itself - the dongle publishes it before B3 / B9, and Home
 * Assistant may deliver them as separate updates - so it ends the request only after ARM_OFF_GRACE_MS with nothing else said
 * (a repeated identical outcome does not change B9 at all). A periodic re-publish of the same state does NOT count as an answer.
 * With no answer after ACT_PENDING_TIMEOUT_MS it becomes 'timeout' (a message, never a retry).
 */
export function advanceFlow(flow, s) {
  if (!flow) return null;
  if (flow.kind === 'save' && s.review === 'saving') return flow.state === 'running' ? flow : { ...flow, state: 'running' };
  if (flow.state === 'running') return null;
  const answered = s.review !== flow.review0 || s.b9Key !== flow.b9Key;
  if (answered) return null;
  if (flow.armOn && s.armState === false && s.nowMs - flow.atMs >= ARM_OFF_GRACE_MS) return null;
  if (flow.state === 'sent' && s.nowMs - flow.atMs >= ACT_PENDING_TIMEOUT_MS) return { ...flow, state: 'timeout' };
  return flow;
}

// ---- technical detail toggle (per viewer) -----------------------------------
function storageOrNull() {
  try {
    return typeof localStorage !== 'undefined' ? localStorage : null;
  } catch (e) {
    return null;
  }
}
export function readLocalDetail(storage) {
  try {
    const s = storage === undefined ? storageOrNull() : storage;
    return !!s && s.getItem(DETAIL_STORAGE_KEY) === '1';
  } catch (e) {
    return false;
  }
}
export function writeLocalDetail(on, storage) {
  try {
    const s = storage === undefined ? storageOrNull() : storage;
    if (!s) return false;
    s.setItem(DETAIL_STORAGE_KEY, on ? '1' : '0');
    return true;
  } catch (e) {
    return false;
  }
}
/** The helper (when configured and reporting on/off) wins; otherwise the per-viewer value. */
export function resolveDetail({ helperState, local }) {
  if (helperState === 'on') return true;
  if (helperState === 'off') return false;
  return !!local;
}

// ---- clipboard ---------------------------------------------------------------
export async function copyToClipboard(text, env = {}) {
  const nav = env.navigator !== undefined ? env.navigator : typeof navigator !== 'undefined' ? navigator : undefined;
  try {
    if (nav && nav.clipboard && typeof nav.clipboard.writeText === 'function') {
      await nav.clipboard.writeText(text);
      return 'copied';
    }
  } catch (e) {
    /* fall through to the text-selection fallback */
  }
  try {
    const doc = env.document !== undefined ? env.document : typeof document !== 'undefined' ? document : undefined;
    if (doc && doc.body && typeof doc.createElement === 'function') {
      const ta = doc.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.cssText = 'position:fixed;top:-1000px;left:-1000px;opacity:0';
      doc.body.appendChild(ta);
      ta.select();
      const done = typeof doc.execCommand === 'function' ? doc.execCommand('copy') : false;
      doc.body.removeChild(ta);
      if (done) return 'copied';
    }
  } catch (e) {
    /* nothing more to try */
  }
  return 'unsupported';
}

// ===========================================================================
// 6. HTML renderers (pure functions returning strings)
// ===========================================================================
export const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

// Icons: simple geometric shapes drawn for this card (24 x 24 viewBox, even-odd fill), not taken from any icon set.
const ICON = {
  cert:
    'M5 3h10l4 4v14H5ZM7 5h7v3h3v11H7ZM9 12h6v1.5H9ZM9 15h6v1.5H9Z',
  check:
    'M3 12a9 9 0 1 0 18 0a9 9 0 1 0-18 0ZM5 12a7 7 0 1 0 14 0a7 7 0 1 0-14 0ZM7.5 12.5 9 11l2 2 4-4 1.5 1.5-5.5 5.5Z',
  alert:
    'M3 12a9 9 0 1 0 18 0a9 9 0 1 0-18 0ZM5 12a7 7 0 1 0 14 0a7 7 0 1 0-14 0ZM11 7h2v6h-2ZM11 15h2v2h-2Z',
  close:
    'M3 12a9 9 0 1 0 18 0a9 9 0 1 0-18 0ZM5 12a7 7 0 1 0 14 0a7 7 0 1 0-14 0ZM8.5 9.9 9.9 8.5 12 10.6l2.1-2.1 1.4 1.4-2.1 2.1 2.1 2.1-1.4 1.4-2.1-2.1-2.1 2.1-1.4-1.4 2.1-2.1Z',
  help:
    'M3 12a9 9 0 1 0 18 0a9 9 0 1 0-18 0ZM5 12a7 7 0 1 0 14 0a7 7 0 1 0-14 0ZM9 7h6v5h-2v2h-2v-4h2V9H9ZM11 15h2v2h-2Z',
  clock:
    'M3 12a9 9 0 1 0 18 0a9 9 0 1 0-18 0ZM5 12a7 7 0 1 0 14 0a7 7 0 1 0-14 0ZM11 7h2v5h3v2h-5Z',
  search:
    'M10 4a6 6 0 1 0 0 12a6 6 0 1 0 0-12ZM10 6a4 4 0 1 0 0 8a4 4 0 1 0 0-8ZM14.2 15.6l1.4-1.4 4.9 4.9-1.4 1.4Z',
  finger:
    'M3 12a9 9 0 1 0 18 0a9 9 0 1 0-18 0ZM4.5 12a7.5 7.5 0 1 0 15 0a7.5 7.5 0 1 0-15 0ZM7 12a5 5 0 1 0 10 0a5 5 0 1 0-10 0ZM8.5 12a3.5 3.5 0 1 0 7 0a3.5 3.5 0 1 0-7 0ZM10.5 12a1.5 1.5 0 1 0 3 0a1.5 1.5 0 1 0-3 0Z',
  shieldcheck:
    'M12 2l8 3v7l-8 10-8-10V5ZM12 4.2l6 2.2v5l-6 7.6-6-7.6v-5ZM8.5 11.5 10 10l1.5 1.5L14.5 8.5 16 10l-4.5 4.5Z',
  table:
    'M3 4h18v16H3ZM5 6h6v4H5ZM13 6h6v4h-6ZM5 12h6v6H5ZM13 12h6v6h-6Z',
  code:
    'M8.6 7 10 8.4 6.4 12 10 15.6 8.6 17l-5-5ZM15.4 7 14 8.4l3.6 3.6-3.6 3.6 1.4 1.4 5-5Z',
  savelock:
    'M4 3h12l4 4v14H4ZM6 5h2v4h7V5h.4L18 7.6V19H6ZM10 13h4v4h-4Z',
  key:
    'M7 8a4 4 0 1 0 0 8a4 4 0 1 0 0-8ZM7 10.5a1.5 1.5 0 1 0 0 3a1.5 1.5 0 1 0 0-3ZM11 11h10v2h-2v3h-2v-3h-6Z',
  restore:
    'M9 6v3h6a4 4 0 0 1 0 8H9v-2h6a2 2 0 0 0 0-4H9v3L4 9.5Z',
  pause:
    'M8 3h8l5 5v8l-5 5H8l-5-5V8ZM8.8 5h6.4L19 8.8v6.4L15.2 19H8.8L5 15.2V8.8ZM9.5 8.5h2v7h-2ZM12.5 8.5h2v7h-2Z',
  play:
    'M12 2l8 3v7l-8 10-8-10V5ZM12 4.2l6 2.2v5l-6 7.6-6-7.6v-5ZM10 8.5v6l5-3Z',
  heart:
    'M2 11h5l2-5 4 10 2-5h7v2h-5.6L13 19.5 9 9.9 8.3 13H2Z',
  lock:
    'M8 10V7a4 4 0 0 1 8 0v3h-2V7a2 2 0 0 0-4 0v3ZM5 10h14v11H5ZM11 14h2v3h-2Z',
  timer:
    'M6 2h12v2h-1v3l-3.5 5 3.5 5v3h1v2H6v-2h1v-3l3.5-5L7 7V4H6Z',
  shieldrefresh:
    'M12 2l8 3v7l-8 10-8-10V5ZM12 4.2l6 2.2v5l-6 7.6-6-7.6v-5ZM9 9h4V8l2.5 2-2.5 2v-1H9ZM15 14h-4v1l-2.5-2 2.5-2v1h4Z',
};
const svg = (name, cls = '') =>
  `<svg class="${cls}" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" focusable="false"><path fill-rule="evenodd" d="${ICON[name]}"/></svg>`;

const COLOR = { ok: 'var(--ok)', warn: 'var(--warn)', bad: 'var(--bad)', idle: 'var(--idle)', busy: 'var(--busy)', future: 'var(--future)' };
const TONE_VAR = { ok: 'var(--ok)', warn: 'var(--warn)', bad: 'var(--bad)', neutral: 'var(--text-2)' };

/** A placeholder the 1 Hz tick fills in place (keeps the rest of the DOM, focus and live regions still). */
const ph = (key) => `<span data-t="${key}"></span>`;

/** Substitute the time placeholders (used by tests and the first paint). */
export function fillTime(html, tv) {
  const t = timeTexts(tv);
  return html.replace(
    /<span([^>]*?)\sdata-t="(\w+)"([^>]*)><\/span>/g,
    (_, a, k, b) => `<span${a} data-t="${k}"${b}>${esc(t[k] === undefined ? '' : t[k])}</span>`,
  );
}

/** Check and gate details carry `@rem@` (candidate) and `@arm@` (arm) markers for the live remaining time. */
const withRem = (detail) => esc(detail).replace(/@rem@/g, ph('rem')).replace(/@arm@/g, ph('arm'));

export function makeFormatters({ locale, timeZone } = {}) {
  const dateTime = (sec) => {
    const opts = { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' };
    try {
      return new Date(sec * 1000).toLocaleString(locale, timeZone ? { ...opts, timeZone } : opts);
    } catch (e) {
      return new Date(sec * 1000).toISOString().slice(0, 16).replace('T', ' ');
    }
  };
  const time = (ms) => {
    const opts = { hour: '2-digit', minute: '2-digit', second: '2-digit' };
    try {
      return new Date(ms).toLocaleTimeString(locale, timeZone ? { ...opts, timeZone } : opts);
    } catch (e) {
      return new Date(ms).toISOString().slice(11, 19);
    }
  };
  return { dateTime, time };
}

const eyebrow = (n, text, icon, right = '') =>
  `<div class="eyebrow">${svg(icon)}<span>${n} · ${esc(text)}</span><span class="right">${right}</span></div>`;
const head = (word, pulse = false, fk = '') =>
  `<div class="head"${fk ? ` tabindex="-1" data-fk="${fk}"` : ''}><span class="dot${pulse ? ' pulse' : ''}"></span><span class="headline">${esc(word)}</span></div>`;
const chip = (cls, text, title = '') =>
  `<span class="chip ${cls}"${title ? ` title="${esc(title)}"` : ''}>${esc(text)}</span>`;
const pill = (label, attrs) => `<button type="button" class="pill" ${attrs}>${esc(label)}</button>`;

/**
 * A card render result. `inner` may be an array of top-level element strings
 * ("kids"): only the review card passes one, so the patcher can keep its
 * live regions and the focused button in place between renders.
 */
function cardOut(cls, tone, inner, attrs = {}) {
  const kids = Array.isArray(inner) ? inner : null;
  return { cls, state: COLOR[tone] || tone, inner: kids ? kids.join('') : inner, kids, attrs };
}

/** `live:<key>` / `morph:<key>` when the kid's root element carries data-live / data-morph, else null. */
const patchKey = (html) => {
  const m = /^<[a-z][a-z0-9]*[^>]*\sdata-(live|morph)="([^"]*)"/.exec(html);
  return m ? `${m[1]}:${m[2]}` : null;
};

/**
 * Patch plan between two renders of one card's kids. Returns null when the
 * whole card must be replaced, else one op per kid: 'keep' (identical),
 * 'live' (same persistent live region: update its content in place, so a
 * screen reader announces the change), 'morph' (same keyed body: patch the
 * existing nodes in place, see morphNode) or 'replace'.
 */
export function planPatch(prev, next) {
  if (!Array.isArray(prev) || !Array.isArray(next) || prev.length !== next.length) return null;
  return next.map((html, i) => {
    if (prev[i] === html) return 'keep';
    const k = patchKey(html);
    if (k === null || k !== patchKey(prev[i])) return 'replace';
    return k.startsWith('live:') ? 'live' : 'morph';
  });
}

// ---- in-place DOM patching ---------------------------------------------------------
/**
 * Set a text node to `text` with the smallest replaceData(): only the characters that differ are touched, so
 * a text selection that spans an unchanged part of the string (the raw B3 string while only its countdown
 * digits change) survives the update. Returns true when the text changed.
 */
export function setText(node, text) {
  const cur = node.nodeValue;
  if (cur === text) return false;
  if (typeof node.replaceData !== 'function') {
    node.nodeValue = text;
    return true;
  }
  const max = Math.min(cur.length, text.length);
  let p = 0;
  while (p < max && cur.charCodeAt(p) === text.charCodeAt(p)) p += 1;
  let s = 0;
  while (s < max - p && cur.charCodeAt(cur.length - 1 - s) === text.charCodeAt(text.length - 1 - s)) s += 1;
  node.replaceData(p, cur.length - p - s, text.slice(p, text.length - s));
  return true;
}

function syncAttributes(o, n) {
  for (const a of Array.from(o.attributes)) if (!n.hasAttribute(a.name)) o.removeAttribute(a.name);
  for (const a of Array.from(n.attributes)) if (o.getAttribute(a.name) !== a.value) o.setAttribute(a.name, a.value);
}

/**
 * Make the live node `o` equal to the freshly parsed node `n`, keeping every live node whose type and tag
 * already match (children are matched by position; the card-7 structure is the same every render, only
 * its text and the vector rows vary). A node that cannot be kept is replaced by the parsed one, which is
 * MOVED out of its template. Returns the node now in the document at that position.
 */
export function morphNode(o, n) {
  if (o.nodeType !== n.nodeType || o.nodeName !== n.nodeName) {
    o.replaceWith(n);
    return n;
  }
  if (o.nodeType === 3) {
    setText(o, n.nodeValue);
    return o;
  }
  syncAttributes(o, n);
  const oc = Array.from(o.childNodes);
  const nc = Array.from(n.childNodes);
  const common = Math.min(oc.length, nc.length);
  for (let i = 0; i < common; i += 1) morphNode(oc[i], nc[i]);
  for (let i = common; i < oc.length; i += 1) o.removeChild(oc[i]);
  for (let i = common; i < nc.length; i += 1) o.appendChild(nc[i]);
  return o;
}

// ---- top bar ------------------------------------------------------------------
export function renderHeader(vm, ui) {
  if (!ui.showHeader) return '';
  const badge = (label, val, on, off, icon, warnOff = true) => {
    const c = val === null ? 'var(--idle)' : val ? 'var(--ok)' : warnOff ? 'var(--warn)' : 'var(--idle)';
    const txt = val === null ? 'unavailable' : val ? on : off;
    return `<span class="badge">${svg(icon)}${esc(label)} <span class="dot" style="background:${c}"></span> ${esc(txt)}</span>`;
  };
  const supOff = vm.sup.state ? String(vm.sup.state).toLowerCase() : 'not stable';
  return (
    `<div class="topbar"><h2>${svg('shieldrefresh')} ${esc(ui.title)}</h2><div class="badges" role="group" aria-label="Safety signals">` +
    badge('Supervision', vm.sup.stable, 'stable', supOff, 'heart') +
    badge('NTP', vm.ntp, 'synced', 'not synced', 'clock') +
    badge('Write lock', vm.wl === null ? null : !vm.wl, 'free', 'held', 'lock') +
    `</div></div>`
  );
}

// ---- guarded Save / Invalidate: shared pieces ----------------------------------------------------------
// A confirmation panel is DERIVED from live state (the arm switch reports on, the candidate or profile is on screen),
// never from a click that has not been echoed. Its buttons carry the ID that was on screen when they were drawn; the
// click handler compares it with the current ID before anything is sent.
const GATE_ICON = { pass: 'check', fail: 'close', unknown: 'help' };
const GATE_WORD = { pass: 'passed', fail: 'not met', unknown: 'unknown' };

/** The gate items as a check list (the same markup as card 5). */
function gateList(items) {
  const rows = items
    .map(
      (it) =>
        `<div class="check ${it.state}">${svg(GATE_ICON[it.state])}<div><div class="l">${esc(it.label)}<span class="sr"> - ${GATE_WORD[it.state]}</span></div>` +
        `<div class="d">${withRem(it.detail)}</div></div></div>`,
    )
    .join('');
  return `<div class="checks">${rows}</div>`;
}

// FB-B2 (CARD-02): every gate reason can carry entity text (the supervision state, for one), so a reason reaches the markup ONLY through
// these two helpers and withRem, each of which escapes: a title attribute and a note line. No reason is interpolated raw anywhere.
const titleAttr = (text) => (text ? ` title="${esc(text)}"` : '');
const noteDiv = (text) => `<div class="caption warnnote">${esc(text)}</div>`;
const noticeRow = (ui) => (ui.notice ? noteDiv(ui.notice) : '');
const warnRow = (t) => `<div class="warnrow">${svg('alert')}<span>${esc(t)}</span></div>`;
const badRow = (t) => `<div class="badrow">${svg('close')}<span>${esc(t)}</span></div>`;
const sentenceP = (t) => `<p class="sentence">${esc(t)}</p>`;
const kvRows = (pairs) =>
  `<div class="rows">${pairs.map(([k, v, cls = '']) => `<span class="k">${esc(k)}</span><span class="v${cls ? ` ${cls}` : ''}">${v}</span>`).join('')}</div>`;
const progressRow = (text) =>
  `<div class="progress" role="status" aria-busy="true" tabindex="-1" data-fk="flow-status"><span class="spin" aria-hidden="true"></span><span>${esc(text)}</span></div>`;
const armCount = () => `<div class="armcount">${svg('timer')}<span>Arm timer: ${ph('arm')}</span></div>`;

/** A request this card sent that is not answered yet ('timeout' / 'unsure'): a message, never a retry. */
function flowWarning(flow) {
  if (!flow || (flow.state !== 'timeout' && flow.state !== 'unsure')) return '';
  const T = FLOW_TEXT;
  if (flow.state === 'unsure') return warnRow(T.notAccepted);
  return warnRow(flow.kind === 'invalidate' ? T.noResultInvalidate : T.noResult);
}

/**
 * The last Save / Invalidate outcome as {word, tone, html}, or null when B9 is not one. SAVE_UNCONFIRMED guidance:
 * do not repeat the request, and restart the dongle only when no temporary operation is active.
 */
export function actResult(vm, env) {
  const a = vm.act;
  if (!a || a.outcome === 'progress') return null;
  const T = FLOW_TEXT;
  const num = (n) => (n === null ? '—' : String(n));
  switch (`${a.family}:${a.outcome}`) {
    case 'save:saved': {
      const when = vm.at === null ? '—' : vm.at === 0 ? 'capture time unknown' : env.dateTime(vm.at);
      const lead = a.verified ? `${T.savedOk}: generation ${num(a.gen)}${vm.at ? `, ${when}` : ''}.` : T.savedUnverified;
      const pairs = [['Generation', esc(num(a.gen))]];
      if (a.verified) pairs.push(['Saved', esc(when)], ['ID', esc(vm.idHex ? vm.idHex.slice(0, 8) : '—'), 'mono']);
      return { word: 'SAVED', tone: 'ok', html: sentenceP(lead) + kvRows(pairs) };
    }
    case 'save:refused':
      return { word: 'SAVE REFUSED', tone: 'warn', html: warnRow(a.detail) + sentenceP(T.saveRefusedTail) };
    case 'save:notcommitted':
      return { word: 'SAVE NOT COMMITTED', tone: 'bad', html: badRow(a.detail) + sentenceP(a.witness ? T.saveWitness : T.saveNotCommitted) };
    case 'save:unknown':
      return { word: 'SAVE OUTCOME UNKNOWN', tone: 'bad', html: badRow(a.detail) + sentenceP(T.saveUnknown) };
    case 'invalidate:invalidated': {
      const pairs = [['Invalidated generation', esc(num(a.gen))], ['Record is now generation', esc(num(a.newGen))]];
      // FB-B2 (CARD-11): "Invalidated: ..." only when B1, B2 (generation, witness, operation, storage error) and B9 agree
      return { word: 'INVALIDATED', tone: 'ok', html: sentenceP(a.verified ? T.invalidatedOk : T.invalidatedUnverified) + kvRows(pairs) };
    }
    case 'invalidate:refused':
      return { word: 'INVALIDATE REFUSED', tone: 'warn', html: warnRow(a.detail) + sentenceP(T.invalidateRefusedTail) };
    case 'invalidate:notcommitted':
      return {
        word: 'INVALIDATE NOT COMMITTED',
        tone: 'bad',
        html: badRow(a.detail) + sentenceP(a.witness ? T.invalidateWitness : T.invalidateNotCommitted),
      };
    case 'invalidate:unknown':
      return { word: 'INVALIDATE OUTCOME UNKNOWN', tone: 'bad', html: badRow(a.detail) + sentenceP(T.invalidateUnknown) };
    case 'other:refused':
      return { word: 'REFUSED', tone: 'warn', html: warnRow(a.detail) + sentenceP(T.actionRefused) };
    default:
      return null;
  }
}

/** What is stored right now, from the saved-profile summary (B2 g and at) and the candidate's prior class. */
export function storedNowText(vm, env) {
  const when = vm.at === null ? '' : vm.at === 0 ? ', capture time unknown' : `, saved ${env.dateTime(vm.at)}`;
  switch (vm.prior) {
    case 'NOT_CAPTURED':
      return 'Nothing is stored yet';
    case 'PROFILE_LOST':
      return `The profile is missing${vm.hw === null ? '' : ` (last known generation ${vm.hw})`}`;
    case 'CORRUPT':
      return 'A damaged profile that cannot be read';
    default:
      return vm.g === null ? `${vm.prior || 'Unknown'}` : `${vm.prior} profile, generation ${vm.g}${when}`;
  }
}

/** The confirmation panel of a save: the candidate ID being confirmed, what the save does, every prerequisite, the arm timer. */
function saveConfirm(vm, ui, gate, env) {
  const T = FLOW_TEXT;
  const rc = gate.variant === 'replace_corrupt';
  const eff = gate.effect;
  const blocked = !gate.allowed;
  const rows = kvRows([
    ['ID being confirmed', esc(groupId(gate.id)), 'mono'],
    ['Stored now', esc(storedNowText(vm, env))],
    ['What happens', esc(eff ? eff.sentence : '—')],
    ['Expected generation', esc(eff && eff.gen !== null ? String(eff.gen) : '—')],
    ['Confirmation', esc(gate.phrase), 'mono phrase'],
  ]);
  return (
    `<div class="confirm" role="group" aria-labelledby="confirm-save-title" data-act="stay" data-confirm="save">` +
    `<div class="ctitle" id="confirm-save-title" tabindex="-1" data-fk="confirm-save-title">${esc(rc ? T.titleReplace : T.titleSave)}</div>` +
    sentenceP(rc ? T.introReplace : T.introSave) +
    rows +
    gateList(gate.items) +
    armCount() +
    `<div class="footrow"><button type="button" class="btn go" data-act="save" data-fk="save" data-id="${esc(gate.id || '')}" data-variant="${gate.variant}" ` +
    `aria-disabled="${blocked}"${blocked ? titleAttr(gate.why) : ''}>${svg('savelock')} ${esc(rc ? T.replace : T.save)}</button>` +
    `<button type="button" class="btn quiet" data-act="arm-cancel" data-fk="arm-cancel">${svg('close')} ${esc(T.cancel)}</button></div>` +
    (blocked && gate.why ? noteDiv(gate.why) : '') +
    `<div class="caption">${esc(T.oneShot)}</div>` +
    noticeRow(ui) +
    `</div>`
  );
}

/** The confirmation panel of an invalidate: the stored profile's full 16-hex binding and the phrase that is sent. */
function invalidateConfirm(vm, ui, gate) {
  const T = FLOW_TEXT;
  const blocked = !gate.allowed;
  const rows = kvRows([
    ['ID being confirmed', esc(groupId(gate.id)), 'mono'],
    ['Generation', esc(vm.g === null ? '—' : String(vm.g))],
    ['Confirmation', esc(gate.phrase), 'mono phrase'],
  ]);
  return (
    `<div class="confirm inv" role="group" aria-labelledby="confirm-inv-title" data-act="stay" data-confirm="invalidate">` +
    `<div class="ctitle" id="confirm-inv-title" tabindex="-1" data-fk="confirm-inv-title">${esc(T.titleInvalidate)}</div>` +
    sentenceP(T.introInvalidate) +
    (gate.discardsCandidate ? sentenceP(T.discardsCandidate) : '') +
    rows +
    gateList(gate.items) +
    armCount() +
    `<div class="footrow"><button type="button" class="btn go" data-act="invalidate" data-fk="invalidate" data-id="${esc(gate.id || '')}" ` +
    `aria-disabled="${blocked}"${blocked ? titleAttr(gate.why) : ''}>${svg('alert')} ${esc(T.invalidate)}</button>` +
    `<button type="button" class="btn quiet" data-act="arm-cancel" data-fk="arm-cancel-inv">${svg('close')} ${esc(T.cancel)}</button></div>` +
    (blocked && gate.why ? noteDiv(gate.why) : '') +
    `<div class="caption">${esc(T.oneShotInvalidate)}</div>` +
    noticeRow(ui) +
    `</div>`
  );
}

/** The arm is on but no confirmation panel is open for it (no candidate, or it is set for the other action). */
function armStrip(vm, ui) {
  if (!vm.arm.configured || vm.arm.state !== true) return '';
  const T = FLOW_TEXT;
  // FB-B2 (CARD-08): what the strip says depends on who switched the arm on. intent 'save': this card, for a save (no candidate to confirm
  // now); 'invalidate': this card, for an invalidate; 'sent': a request of this card that has already used the arm up; null: nobody here
  // (another tab or user, the Home Assistant UI, a reload)
  const text = ui.intent === 'invalidate' ? T.armForInvalidate : ui.intent === 'save' ? T.armIsOn : ui.intent === 'sent' ? T.armSpent : T.armElsewhere;
  return (
    `<div class="armstrip" data-act="stay"><span>${svg('key')} ${esc(text)} Arm timer: ${ph('arm')}</span>` +
    `<button type="button" class="btn quiet" data-act="arm-cancel" data-fk="arm-cancel-strip">${esc(T.turnOff)}</button></div>`
  );
}

/** Saved profile card, below the rows: the guarded Invalidate control and the last Invalidate outcome. */
function invalidateBlock(vm, ui, env, tv) {
  const T = FLOW_TEXT;
  const flow = ui.flow && ui.flow.kind === 'invalidate' ? ui.flow : null;
  if (flow && flow.state === 'sent') {
    return `<div class="actblock" data-act="stay">${progressRow(T.invalidateSent)}${kvRows([['Profile ID', esc(groupId(flow.id)), 'mono']])}</div>`;
  }
  let out = '';
  const res = vm.act && vm.act.family === 'invalidate' ? actResult(vm, env) : null;
  if (res) {
    out += `<div class="actres ${res.tone}" data-act="stay"><div class="at" tabindex="-1" data-fk="act-result-inv">${esc(res.word)}</div>${res.html}</div>`;
  }
  out += flowWarning(flow);
  if (vm.profile === 'saved' && vm.arm.configured) {
    const gate = invalidateGate(vm, tv, { pending: !!flowPendingKind(ui.flow), cancelling: !!ui.cancelling });
    if (vm.arm.state === true && ui.intent === 'invalidate' && !ui.cancelling) out += invalidateConfirm(vm, ui, gate);
    else {
      const bs = armButtonState(gate, vm, { pending: !!ui.armPending && ui.intent === 'invalidate', kind: 'invalidate', cancelling: !!ui.cancelling });
      out +=
        `<div class="actblock" data-act="stay"><button type="button" class="btn quiet" data-act="arm-invalidate" data-fk="arm-invalidate" aria-disabled="${bs.disabled}"` +
        `${titleAttr(bs.why)}>${svg('key')} ${esc(ui.armPending && ui.intent === 'invalidate' ? T.arming : T.armInvalidate)}</button>` +
        `<div class="caption">${esc(T.armCaption)}</div>` +
        (bs.disabled && bs.why ? noteDiv(bs.why) : '') +
        `${noticeRow(ui)}</div>`;
    }
  }
  return out;
}

// ---- card 1: saved profile ------------------------------------------------------
export function renderProfile(vm, ui, env, tv) {
  let word;
  let tone;
  let sentence;
  switch (vm.profile) {
    case 'saved': {
      word = 'SAVED';
      tone = 'ok';
      const gen = vm.g === null ? 'Known-good profile' : `Known-good profile generation ${vm.g}`;
      if (vm.at === null) sentence = `${gen}.`;
      else if (vm.at === 0) sentence = `${gen} (capture time unknown).`;
      else sentence = `${gen}, saved ${env.dateTime(vm.at)}.`;
      break;
    }
    case 'notsaved':
      word = 'NOT SAVED';
      tone = 'idle';
      sentence = SENTENCE.notSaved;
      break;
    case 'invalidated':
      word = 'INVALIDATED';
      tone = 'warn';
      sentence = SENTENCE.invalidated;
      break;
    case 'unusable':
      word = 'UNUSABLE';
      tone = 'bad';
      sentence = unusableSentence(vm.b1, vm.hw);
      break;
    case 'unrecognised':
      word = 'UNRECOGNISED';
      tone = 'idle';
      sentence = `Unrecognised Fallback Profile state '${vm.b1}' — check that firmware and dashboard versions match.`;
      break;
    default:
      word = 'NOT REPORTING';
      tone = 'idle';
      sentence = SENTENCE.notReporting;
  }
  let rows = '';
  if (vm.profile !== 'unavailable' && vm.profile !== 'unrecognised') {
    const date = vm.at === null ? '—' : vm.at === 0 ? 'capture time unknown' : env.dateTime(vm.at);
    rows =
      `<div class="rows"><span class="k">Generation</span><span class="v">${vm.g === null ? 'none' : vm.g}</span>` +
      `<span class="k">Saved</span><span class="v">${esc(date)}</span>` +
      `<span class="k">ID</span><span class="v mono">${vm.idHex ? vm.idHex.slice(0, 8) : '—'}</span>`;
    if (vm.profile === 'unusable' && vm.b2) {
      const df = vm.b2.df !== '-' ? `<div>defect: ${esc(own(DF_TEXT, vm.b2.df) || vm.b2.df)}</div>` : '';
      rows +=
        `<span class="k">Storage</span><span class="v" title="${esc(`ld=${vm.b2.ld} df=${vm.b2.df} w=${vm.b2.w}`)}">` +
        `<div>${esc(own(LD_TEXT, vm.b2.ld) || vm.b2.ld)}</div>${df}<div>witness: ${esc(own(W_TEXT, vm.b2.w) || vm.b2.w)}</div></span>`;
    } else if (vm.profile === 'saved' && vm.b2 && (vm.b2.w === 'LAG' || vm.b2.w === 'MISS' || vm.b2.w === 'CORR')) {
      rows +=
        `<span class="k">Witness</span><span class="v" style="color:var(--warn)" title="${esc(`w=${vm.b2.w}`)}">` +
        `${esc(own(W_TEXT, vm.b2.w))} - saving again would repair it</span>`;
    }
    rows += `</div>`;
  }
  const more = ui.moreInfoEnabled
    ? pill('details', 'data-act="more-info" data-ent="profile_state" data-fk="more-c1" title="Open the Saved Profile entity"')
    : '';
  const inner =
    eyebrow(1, 'Saved profile', 'cert', more) +
    head(word, false, 'c1-head') +
    `<p class="sentence">${esc(sentence)}</p>` +
    rows +
    invalidateBlock(vm, ui, env, tv || timeView(null, 0));
  return cardOut('big tinted', tone, inner, { 'data-act': 'more-info', 'data-ent': 'profile_state' });
}

// ---- card 2: live match ---------------------------------------------------------
export function renderLive(vm, ui, env, tv) {
  const lm = liveMatch(vm, tv);
  const sentence = lm.sentence
    .map((p) => (p === 'age' ? (tv.has ? ph('age') : '—') : esc(p)))
    .join('');
  const chips = lm.chips.length
    ? `<div class="chiprow">${lm.chips.map((n) => chip('warn', n)).join('')}${lm.more ? chip('warn', `+${lm.more} more`) : ''}</div>`
    : '';
  const basis = lm.basis === 'review' && tv.has ? `Basis: review ${ph('age')} ago` : 'Basis: none';
  const jump = vm.candOK ? pill('values', 'data-act="goto-summary" data-fk="goto-c6" title="Show the candidate values"') : '';
  const inner =
    eyebrow(2, 'Live match', lm.icon, jump) +
    head(lm.word, lm.word === 'CHECKING') +
    `<p class="sentence">${sentence}</p>` +
    chips +
    `<div class="caption">${basis}</div>`;
  return cardOut('big tinted', lm.tone, inner, vm.candOK ? { 'data-act': 'goto-summary' } : {});
}

// ---- card 3: review current configuration ------------------------------------------
function stepperFor(vm) {
  const steps = [
    { label: 'Read pass 1', cls: '', style: '' },
    { label: 'Read pass 2', cls: '', style: '' },
    { label: 'Compare', cls: '', style: '' },
    { label: 'Candidate', cls: '', style: '' },
  ];
  const on = (i, col, extra = '') => {
    steps[i].cls = `on ${extra}`.trim();
    steps[i].style = `--sc:${col}`;
  };
  let rail = '';
  let caption = '';
  let state = 'Nothing read yet';
  switch (vm.review) {
    case 'reading':
      on(0, 'var(--busy)', 'pulse');
      on(1, 'var(--busy)');
      on(2, 'var(--busy)');
      rail = 'rail-busy';
      caption = '4 reads in progress · read-only';
      state = 'Reading';
      break;
    case 'saving':
      // the dongle re-reads the inverter (the same four reads), then writes the profile record: no inverter write
      on(0, 'var(--busy)', 'pulse');
      on(1, 'var(--busy)');
      on(2, 'var(--busy)');
      steps[3].label = 'Commit';
      rail = 'rail-busy';
      caption = '4 reads, then the profile record is written · no inverter write';
      state = 'Saving';
      break;
    case 'ready':
      [0, 1, 2, 3].forEach((i) => on(i, 'var(--ok)'));
      state = 'Candidate ready';
      break;
    case 'notsaveable':
      [0, 1, 2].forEach((i) => on(i, 'var(--ok)'));
      on(3, 'var(--warn)');
      steps[3].label = 'not saveable';
      state = 'Candidate not saveable';
      break;
    case 'mismatch':
      on(0, 'var(--ok)');
      on(1, 'var(--ok)');
      on(2, 'var(--bad)');
      steps[2].label = 'differs';
      state = 'Configuration changed during the read';
      break;
    case 'readerror':
      if (vm.b9.busy) {
        steps[0].cls = 'slash';
        steps[0].label = 'bus busy';
        caption = 'The inverter bus stayed busy; nothing was read.';
      } else {
        on(0, 'var(--bad)');
        on(1, 'var(--bad)');
        steps[1].label = 'not completed';
        if (vm.b9.block) caption = `Read of registers ${vm.b9.block} not completed.`;
      }
      state = 'Read not completed';
      break;
    case 'refused':
      steps[0].cls = 'slash';
      steps[0].label = 'refused before reading';
      state = 'Refused before reading';
      break;
    case 'expired':
    case 'cleared':
      steps[3].cls = 'strike';
      steps[3].label = vm.review;
      state = `Candidate ${vm.review}`;
      break;
    default:
  }
  return { steps, rail, caption, state };
}

function reviewTexts(vm, tv) {
  const detail = vm.b9.detail || vm.b9.raw;
  switch (vm.review) {
    case 'available':
      return { word: 'REVIEW AVAILABLE', tone: 'idle', html: esc(SENTENCE.reviewAvailable) };
    case 'reading':
      return { word: 'READING INVERTER', tone: 'busy', html: esc(SENTENCE.reviewReading) };
    case 'saving':
      return { word: 'SAVING', tone: 'busy', html: esc(SENTENCE.saving) };
    case 'ready': {
      const tail =
        tv.has && tv.bucket !== 'zero'
          ? `<span aria-live="off">Candidate expires in ${ph('rem')}.</span>`
          : tv.has
            ? '<span aria-live="off">Candidate is expiring; waiting for the firmware to confirm.</span>'
            : '';
      return { word: 'CANDIDATE READY', tone: 'ok', html: `Both passes agree on all 31 registers. ${tail}`.trim() };
    }
    case 'notsaveable':
      return { word: 'NOT SAVEABLE', tone: 'warn', html: esc(SENTENCE.notSaveable) };
    case 'mismatch':
      return { word: 'CONFIGURATION CHANGED DURING READ', tone: 'bad', html: esc(detail) };
    case 'readerror':
      return { word: 'REVIEW NOT COMPLETED', tone: 'bad', html: esc(detail) };
    case 'refused':
      return { word: 'REVIEW REFUSED', tone: 'bad', html: esc(detail) };
    case 'expired':
      return { word: 'CANDIDATE EXPIRED', tone: 'idle', html: esc(SENTENCE.expired) };
    case 'cleared':
      return { word: 'CANDIDATE CLEARED', tone: 'idle', html: esc(detail) };
    case 'internal':
      return { word: 'INTERNAL STATE RESET', tone: 'bad', html: esc(detail) };
    case 'unrecognised':
      return {
        word: 'UNRECOGNISED STATE',
        tone: 'idle',
        html: esc(`Review status '${vm.st}' is not recognised - check that firmware and dashboard versions match.`),
      };
    default:
      return {
        word: 'NOT REPORTING',
        tone: 'idle',
        html: esc(
          vm.reviewReason === 'malformed'
            ? 'The Review entity reported a value this card cannot read. Check firmware version.'
            : SENTENCE.entitiesUnavailable,
        ),
      };
  }
}

export function renderReview(vm, ui, env, tv) {
  const t = reviewTexts(vm, tv);
  const sp = stepperFor(vm);
  const showCount = (vm.review === 'ready' || vm.review === 'notsaveable') && tv.has;
  const stepsHtml = sp.steps
    .map(
      (s) =>
        `<div class="step ${s.cls}" ${s.style ? `style="${s.style}"` : ''}><span class="c"></span><span>${esc(s.label)}</span></div>`,
    )
    .join('');
  const stepper =
    `<div class="stepper ${sp.rail}" role="group" aria-label="${esc(`Review progress: ${sp.state}`)}">${stepsHtml}` +
    `${sp.caption ? `<div class="caption stepcap">${esc(sp.caption)}</div>` : ''}</div>`;
  const bs = reviewButtonState(vm, { pending: !!ui.pending, act: flowPendingKind(ui.flow) });
  const offline = vm.online === false && !bs.disabled
    ? '<div class="caption warnnote">Configuration polling is offline - a review may not complete.</div>'
    : '';
  const notice = noticeRow(ui);
  const btn =
    `<div class="btnwrap"><button type="button" class="btn" data-act="review" data-fk="review" aria-disabled="${bs.disabled}"` +
    `${titleAttr(bs.why)}>${svg('search')} Review Current Configuration</button>` +
    `<div class="caption" style="margin-top:6px">${esc(SENTENCE.reviewCaption)}</div>` +
    `${bs.why ? noteDiv(bs.why) : ''}${offline}${notice}</div>`;
  const lastText = vm.review === 'unavailable' || !vm.b9Avail ? 'unavailable' : vm.b9.raw;
  const last =
    `<div class="last" data-live="last" aria-live="polite" style="--tone:${TONE_VAR[b9Tone(lastText)]}">` +
    `Last action: <b>${esc(lastText)}</b></div>`;
  const kids = [
    eyebrow(3, 'Review current configuration', 'search'),
    `<div class="live" data-live="head" aria-live="polite">${head(t.word, vm.review === 'reading')}<p class="sentence">${t.html}</p></div>`,
    stepper,
    `<div class="slot">${showCount ? countHtml(tv) : ''}</div>`,
    btn,
    last,
  ];
  return cardOut('big tinted', t.tone, kids);
}

function countHtml(tv) {
  if (!tv.has) return '';
  const col = tv.bucket === 'plenty' ? 'var(--text-2)' : 'var(--warn)';
  const cc = tv.bucket === 'zero' ? 'var(--idle)' : col;
  const pulse = tv.bucket === 'urgent' ? ' pulse' : '';
  const cap =
    tv.bucket === 'zero'
      ? 'waiting for the firmware to confirm expiry'
      : tv.bucket === 'plenty'
        ? 'until the candidate expires'
        : 'expiring soon';
  return (
    `<div class="count" style="--cc:${cc}">${svg('timer')}<span class="n${pulse}" data-t="rem"></span><span class="caption">${cap}</span></div>` +
    `<div class="bar" style="--cc:${col}"><i data-tw></i></div>`
  );
}

// ---- card 4: candidate ------------------------------------------------------------------
/** The rows of a request this card sent, kept on screen while the candidate itself is already consumed. */
function frozenRows(flow, env) {
  return kvRows([
    ['Candidate ID', esc(groupId(flow.id)), 'mono'],
    ['Expected generation', esc(flow.gen === null ? '—' : String(flow.gen))],
    ['Request sent', esc(env.time(flow.atMs))],
  ]);
}

export function renderCandidate(vm, ui, env, tv) {
  let word;
  let tone = 'idle';
  let cls = 'tinted';
  let body = '';
  let strip = true; // the "arm is on" strip is shown unless a confirmation panel already owns the arm
  const warnrow = (code, text) => `<div class="warnrow">${svg('alert')}<span><b>${esc(code)}</b> ${esc(text)}</span></div>`;
  const detail = vm.b9.detail || vm.b9.raw;
  const flow = ui.flow && ui.flow.kind === 'save' ? ui.flow : null;
  const savePending = !!flowPendingKind(ui.flow);
  const result = vm.review === 'available' && vm.act && vm.act.family !== 'invalidate' ? actResult(vm, env) : null;
  if (vm.review === 'unavailable' || vm.review === 'unrecognised') {
    word = 'NOT REPORTING';
    body = `<p class="sentence">${esc(SENTENCE.entitiesUnavailable)}</p>`;
    strip = false;
  } else if (vm.review === 'saving') {
    // B3 st=SAVING: the candidate is already consumed; the rows come from the request this card sent (if it sent it)
    word = 'SAVE IN PROGRESS';
    tone = 'busy';
    strip = false;
    body = progressRow(FLOW_TEXT.running) + (flow ? frozenRows(flow, env) : '') + `<div class="caption">${esc(FLOW_TEXT.doNotRepeat)}</div>`;
  } else if (flow && flow.state === 'sent') {
    word = 'SAVE REQUESTED';
    tone = 'busy';
    strip = false;
    body = progressRow(FLOW_TEXT.sent) + frozenRows(flow, env) + `<div class="caption">${esc(FLOW_TEXT.doNotRepeat)}</div>`;
  } else if (vm.review === 'reading') {
    word = 'BUILDING CANDIDATE';
    tone = 'busy';
    const widths = [62, 48, 36, 44, 70, 56, 40];
    body =
      `<div class="rows">` +
      ['Candidate ID', 'Created', 'Age', 'Expires in', 'Register agreement', 'Eligible to save']
        .map((k, i) => `<span class="k">${k}</span><span class="v"><span class="sk" style="width:${widths[i]}%"></span></span>`)
        .join('') +
      `</div>`;
  } else if (vm.hasCand) {
    word = vm.st === 'CANDIDATE_READY' ? 'CANDIDATE READY' : 'NOT SAVEABLE';
    tone = vm.st === 'CANDIDATE_READY' ? 'ok' : 'warn';
    const created = tv.has ? env.time(tv.createdMs) : '—';
    const idv = vm.reviewId
      ? `<span class="mono" data-raw="id">${vm.reviewId.match(/.{4}/g).join(' ')}</span> ${pill('copy', 'data-act="copy" data-copy-key="id" data-fk="copy-id" aria-label="Copy candidate ID"')}`
      : '—';
    // At zero the firmware still publishes the candidate: the card does not declare it expired (the firmware
    // does that), it says the candidate is expiring and no longer offers a save.
    const zero = tv.has && tv.bucket === 'zero';
    const elig = vm.eligible && !zero;
    const expiring = zero && vm.eligible;
    const expGen = expectedGeneration(vm);
    let becomes = expGen === null ? 'not known: the saved-profile summary is not complete' : `generation ${expGen}`;
    if (expGen !== null && vm.g !== null && vm.prior) becomes += ` (replaces ${vm.prior} generation ${vm.g})`;
    else if (expGen !== null && vm.prior && vm.prior !== 'NOT_CAPTURED') becomes += ` (stored profile ${vm.prior})`;
    body =
      `<div class="rows">` +
      `<span class="k">Candidate ID</span><span class="v">${idv}</span>` +
      `<span class="k">Created</span><span class="v">${esc(created)}</span>` +
      `<span class="k">Age</span><span class="v">${tv.has ? ph('age') : '—'}</span>` +
      `<span class="k">Expires in</span><span class="v">${tv.has ? (zero ? 'expiring…' : ph('rem')) : '—'}</span>` +
      `<span class="k">Register agreement</span><span class="v" style="color:var(--ok)">31 / 31 registers agree</span>` +
      `<span class="k">Eligible to save</span><span class="v" style="color:${elig ? 'var(--ok)' : expiring ? 'var(--warn)' : 'var(--bad)'}">${elig ? 'Yes' : expiring ? 'No (expiring)' : 'No'}</span>` +
      `<span class="k">Would become</span><span class="v">${esc(becomes)}</span></div>`;
    body += countHtml(tv);
    body += vm.blockers.map(badRow).join('');
    if (expiring) body += `<div class="warnrow">${svg('clock')}<span>${esc(EXPIRING_TEXT)}</span></div>`;
    body += vm.notes.map((t) => `<div class="warnrow">${svg('alert')}<span>${esc(t)}</span></div>`).join('');
    body += vm.warnings.map((w) => warnrow(w.code, w.text)).join('');
    body += flowWarning(flow);
    const gate = saveGate(vm, tv, { pending: savePending, cancelling: !!ui.cancelling });
    // FB-B2 (CARD-08): the panel opens only for the arm THIS card switched on for a save (intent 'save'). An arm that is on for any other
    // reason (another tab or user, a reload, an arm a request already used up) shows the strip below, with a way to turn it off.
    const confirmOpen =
      vm.review === 'ready' && vm.arm.configured && vm.arm.state === true && ui.intent === 'save' && !savePending && !ui.cancelling;
    if (confirmOpen) {
      // the confirmation state: derived from the arm switch REPORTING on, never from the click that asked for it
      body += saveConfirm(vm, ui, gate, env);
      strip = false;
    } else {
      const footWord = expiring ? EXPIRING_TEXT : elig ? 'Candidate ready for save' : 'Candidate not saveable';
      const bs = armButtonState(gate, vm, { pending: !!ui.armPending && ui.intent === 'save', cancelling: !!ui.cancelling });
      body +=
        `<div class="footrow"><span style="font-weight:700;color:${elig ? 'var(--ok)' : 'var(--warn)'}">${esc(footWord)}</span>` +
        `<button type="button" class="btn" data-act="arm" data-fk="arm" aria-disabled="${bs.disabled}"${titleAttr(bs.why)}>` +
        `${svg('key')} ${esc(ui.armPending && ui.intent === 'save' ? FLOW_TEXT.arming : FLOW_TEXT.armSave)}</button></div>` +
        `<div class="caption">${esc(FLOW_TEXT.armCaption)}</div>` +
        (bs.disabled && bs.why ? noteDiv(bs.why) : '') +
        noticeRow(ui);
    }
  } else if (vm.review === 'mismatch') {
    word = 'NO CANDIDATE · CONFIGURATION CHANGED';
    tone = 'bad';
    const m = vm.mismatch;
    body =
      (m
        ? `<div class="badrow">${svg('close')}<span>Register ${m.reg}: pass 1 read <b class="mono">${esc(m.a)}</b>, pass 2 read <b class="mono">${esc(m.b)}</b>.</span></div>`
        : badRow(detail)) + '<p class="sentence">Another controller may be editing. Wait a moment and review again.</p>';
  } else if (vm.review === 'readerror') {
    word = 'NO CANDIDATE · READ NOT COMPLETED';
    tone = 'bad';
    body = badRow(detail) + '<p class="sentence">Nothing was written. Review again.</p>';
  } else if (vm.review === 'refused') {
    word = 'NO CANDIDATE · REVIEW REFUSED';
    tone = 'bad';
    body = badRow(detail);
  } else if (vm.review === 'expired') {
    word = 'CANDIDATE EXPIRED';
    cls = 'tinted muted';
    body = '<p class="sentence">Expired after 120 s. The values are no longer shown. Review again.</p>';
  } else if (vm.review === 'cleared') {
    word = 'CANDIDATE CLEARED';
    cls = 'tinted muted';
    body = `<p class="sentence">${esc(detail)}</p>`;
  } else if (vm.review === 'internal') {
    word = 'NO CANDIDATE · INTERNAL STATE RESET';
    tone = 'bad';
    body = badRow(detail);
  } else if (result) {
    // the last Save (or refused action) outcome: terminal until the next Review
    word = result.word;
    tone = result.tone;
    body = result.html;
  } else {
    word = 'NO CANDIDATE';
    body = `<p class="sentence">${esc(SENTENCE.noCandidate)}</p>`;
  }
  if (!vm.hasCand) body += flowWarning(flow);
  if (strip) body += armStrip(vm, ui);
  // FB-B2 (CARD-12): the heading can take focus (data-fk act-result), so the outcome that replaces the progress row receives it
  return cardOut(cls, tone, eyebrow(4, 'Candidate', 'finger') + head(word, false, 'act-result') + body);
}

// ---- card 5: save readiness -----------------------------------------------------------------
export function renderChecks(vm, ui, env, tv) {
  const checks = buildChecks(vm, tv);
  const ic = { pass: 'check', warn: 'alert', fail: 'close', unknown: 'help', pending: 'clock' };
  const word = { pass: 'passed', warn: 'warning', fail: 'not met', unknown: 'unknown', pending: 'in progress' };
  const fail = checks.find((c) => c.state === 'fail');
  const unavailable = vm.review === 'unavailable' || vm.review === 'unrecognised';
  // the live save gate adds what the six checks do not cover (arms, bus, heartbeat state) and the arm itself
  const gate = vm.hasCand ? saveGate(vm, tv, { pending: !!flowPendingKind(ui.flow) }) : null;
  const gateFail = gate ? gate.items.find((it) => it.id !== 'arm' && it.state === 'fail') : null;
  let foot = '';
  if (unavailable) foot = '';
  else if (!vm.hasCand) foot = '<div class="caption">Review first. Checks 1–4 are evaluated at Review; 5–6 are live.</div>';
  else if (fail) {
    foot = `<div class="foot bad">Save would be refused: ${esc(fail.label)}.</div>`;
  } else if (!vm.eligible) {
    foot = `<div class="foot warn">Save would be refused: ${esc(ineligibleReason(vm))} (see candidate).</div>`;
  } else if (gateFail) {
    foot = `<div class="foot bad">Save would be refused: ${esc(gateFail.label)}.</div>`;
  } else if (!gate.allowedToArm) {
    // FB-B2 (CARD-07): something the card needs and cannot see (candidate values, saved-profile summary) is not a plain failure, and not "allowed" either
    foot = `<div class="foot warn">Save is not ready: ${esc(gate.whyToArm)}</div>`;
  } else if (!vm.arm.configured) {
    foot = `<div class="foot warn">${esc(FLOW_TEXT.notSetUp)}</div>`;
  } else if (gate.allowed && ui.intent === 'save') {
    foot = '<div class="foot ok">Save is armed: confirm it in the candidate card.</div>';
  } else if (gate.allowed) {
    // FB-B2 (CARD-08): the arm is on and every prerequisite holds, but not for a save started here: the candidate card shows the strip, no confirmation
    const why = ui.intent === 'invalidate' ? FLOW_TEXT.armForInvalidate : ui.intent === 'sent' ? FLOW_TEXT.armSpentWhy : FLOW_TEXT.armElsewhereWhy;
    foot = `<div class="foot warn">${esc(why)}</div>`;
  } else foot = '<div class="foot ok">Save is allowed once the arm is on: use Arm Save in the candidate card.</div>';
  let tone = 'idle';
  if (!unavailable) {
    if (fail || gateFail) tone = 'bad';
    else if (vm.hasCand) tone = !vm.eligible || !gate.allowedToArm || (gate.allowed && ui.intent !== 'save') || checks.some((c) => c.state === 'warn') ? 'warn' : 'ok';
  }
  const rows = checks
    .map(
      (c) =>
        `<div class="check ${c.state}">${svg(ic[c.state])}<div><div class="l">${esc(c.label)}<span class="sr"> - ${word[c.state]}</span></div>` +
        `<div class="d"${c.tip ? ` title="${esc(c.tip)}"` : ''}>${withRem(c.detail)}</div></div></div>`,
    )
    .join('');
  return cardOut('tinted', tone, eyebrow(5, 'Save readiness', 'shieldcheck') + `<div class="checks">${rows}</div>` + foot);
}

// ---- card 6: configuration summary ------------------------------------------------------------
export function resolveSummaryView(vm, view) {
  let v = view;
  if (v === 'auto' || (v === 'cand' && !vm.candOK) || (v === 'saved' && !vm.savedOK)) {
    v = vm.candOK ? 'cand' : vm.savedOK ? 'saved' : 'none';
  }
  return v;
}

export function renderSummary(vm, ui) {
  const v = resolveSummaryView(vm, ui.view);
  const segBtn = (id, label, enabled, sub, tip = sub) =>
    `<button type="button" data-act="view" data-view="${id}" data-fk="seg-${id}" aria-pressed="${v === id}" aria-disabled="${!enabled}"` +
    `${enabled ? '' : ` title="${esc(tip)}"`}>${esc(label)}${enabled ? '' : `<small>${esc(sub)}</small>`}</button>`;
  const noSaved = savedSegmentNote(vm);
  const seg =
    `<div class="seg" role="group" aria-label="Source">` +
    segBtn('cand', 'Candidate', vm.candOK, 'no candidate') +
    segBtn('saved', vm.savedOK && vm.ssl.g !== null ? `Saved profile g${vm.ssl.g}` : 'Saved profile', vm.savedOK, noSaved.sub, noSaved.tip) +
    `</div>`;
  if (v === 'none') {
    return cardOut(
      '',
      'idle',
      eyebrow(6, 'Configuration summary', 'table', seg) +
        '<p class="sentence">Nothing to show yet. Review the current configuration to see it here.</p>',
    );
  }
  const isCand = v === 'cand';
  const sl = isCand ? vm.sl : vm.ssl;
  const cx = isCand ? vm.cx : vm.scx;
  const ssl = vm.savedOK ? vm.ssl : null;
  const scx = vm.savedOK ? vm.scx : null;
  let any = false;
  const mark = (core, val, was) => {
    if (isCand && core === true) {
      any = true;
      return `<span class="diff">${val}<span class="was">◀ ${esc(was)}</span></span>`;
    }
    return val;
  };
  const dx = isCand ? vm.cmp.dx : '-';
  const dc = isCand ? vm.cmp.dc : '-';
  const di = isCand ? vm.cmp.di : '-';
  const coreOf = (reg) => regDiff(reg, dx, dc, di).core;
  const infoOf = (reg) => regDiff(reg, dx, dc, di).info;
  const onOff = (b, a, z) => (b === null ? '—' : b ? a : z);
  const sv = ssl ? ssl.reg244 : null;
  const tiles =
    `<div class="tiles">` +
    `<div class="tile"><div class="k">Export mode</div><div class="v">${mark(coreOf(244), sl.reg244 === null ? '—' : esc(dec244(sl.reg244)), sv === null ? '—' : dec244(sv))}</div></div>` +
    `<div class="tile"><div class="k">Energy model</div><div class="v">${mark(coreOf(243), cx.r243 === null ? '—' : esc(dec243(cx.r243)), scx && scx.r243 !== null ? dec243(scx.r243) : '—')}</div></div>` +
    `<div class="tile"><div class="k">Grid charging</div><div class="v">${mark(coreOf(232), onOff(bit0(cx.r232), 'On', 'Off'), scx ? onOff(bit0(scx.r232), 'On', 'Off') : '—')}</div></div>` +
    `<div class="tile"><div class="k">TOU schedule</div><div class="v">${mark(coreOf(248), onOff(bit0(cx.r248), 'On', 'Off'), scx ? onOff(bit0(scx.r248), 'On', 'Off') : '—')}</div></div>` +
    `</div>`;
  const rows = sl.slots
    .map((x, i) => {
      if (!x) return `<tr><td class="num">${i + 1}</td><td colspan="5" class="info">not available</td></tr>`;
      const nxt = sl.slots[(i + 1) % 6];
      const sx = ssl ? ssl.slots[i] : null;
      const dsrc = decSrc(x.src);
      const ssrc = sx ? decSrc(sx.src) : null;
      const wasSrc = ssrc ? (ssrc.src !== dsrc.src ? ssrc.src : `${modeText(ssrc)} (mode)`) : '—';
      return (
        `<tr><td class="num">${i + 1}</td>` +
        `<td>${mark(coreOf(250 + i), `${esc(hhmmText(x.hhmm))}–${nxt ? esc(hhmmText(nxt.hhmm)) : '—'}`, sx ? hhmmText(sx.hhmm) : '—')}</td>` +
        `<td class="num">${mark(coreOf(256 + i), `${x.w} W`, sx ? `${sx.w} W` : '—')}</td>` +
        `<td class="num">${mark(coreOf(268 + i), `${x.soc} %`, sx ? `${sx.soc} %` : '—')}</td>` +
        `<td>${mark(coreOf(274 + i), esc(dsrc.src), wasSrc)}<span class="caption mode-fold">${esc(modeText(dsrc))}</span></td>` +
        `<td class="hide-narrow">${esc(modeText(dsrc))}</td></tr>`
      );
    })
    .join('');
  const table =
    `<div class="scrollx" role="region" aria-label="Slot table" tabindex="0" data-fk="scroll-slots"><table><thead><tr>` +
    `<th scope="col" class="num">Slot</th><th scope="col">Window</th><th scope="col" class="num">Power</th>` +
    `<th scope="col" class="num"><span class="lbl-long">Target SOC</span><span class="lbl-short">SOC</span></th>` +
    `<th scope="col">Source</th><th scope="col" class="hide-narrow">Mode</th></tr></thead><tbody>${rows}</tbody></table></div>`;
  const infoLine =
    `<div class="info">Not restored by Fallback V1: grid-charge current ${mark(infoOf(230), cx.r230 === null ? '—' : `${cx.r230} A`, scx && scx.r230 !== null ? `${scx.r230} A` : '—')}` +
    ` · export limit ${mark(infoOf(245), cx.r245 === null ? '—' : String(cx.r245), scx && scx.r245 !== null ? String(scx.r245) : '—')} (not evidence of export limitation)` +
    ` · solar export ${mark(infoOf(247), onOff(bit0(cx.r247), 'on', 'off'), scx ? onOff(bit0(scx.r247), 'on', 'off') : '—')}</div>`;
  const legend = any ? '<div class="legend">◀ = differs from saved profile</div>' : '';
  const ring =
    cx.ring === 'OK'
      ? '<div class="caption" style="color:var(--ok)">Slot times form a valid 24 h ring ✓</div>'
      : cx.ring === 'BAD'
        ? '<div class="caption" style="color:var(--warn)">Slot times are not a valid 24 h ring</div>'
        : '';
  const lead = isCand
    ? 'Values read from the inverter at the last review (both passes agreed).'
    : `Values stored in the saved profile${vm.ssl.g !== null ? ` (generation ${vm.ssl.g})` : ''}.`;
  const caveat =
    !isCand && vm.profile !== 'saved' && vm.b1
      ? `<div class="caption" style="color:var(--warn)">This stored profile is ${esc(vm.b1)} and cannot be used.</div>`
      : '';
  // a candidate that was not compared says so, instead of looking like "no differences" (FW0)
  const notCompared = isCand && notComparedNote(vm);
  const uncompared = notCompared ? `<div class="caption" style="color:var(--warn)">${esc(notCompared)}</div>` : '';
  return cardOut(
    '',
    'idle',
    eyebrow(6, 'Configuration summary', 'table', seg) + `<p class="sentence">${esc(lead)}</p>` + caveat + uncompared + tiles + table + legend + infoLine + ring,
  );
}

// ---- card 7: advanced / raw values -------------------------------------------------------------
export const RAW_ROWS = Object.freeze([
  { key: 'summary', label: 'B2 Summary' },
  { key: 'review', label: 'B3 Review' },
  { key: 'review_id', label: 'B4 Review ID' },
  { key: 'review_slots', label: 'B5 Review Slots' },
  { key: 'review_context', label: 'B6 Review Context' },
  { key: 'saved_slots', label: 'B7 Slots' },
  { key: 'saved_context', label: 'B8 Context' },
  { key: 'last_result', label: 'B9 Last Action-Result' },
]);

/**
 * Card 7 is rendered as two kids: the eyebrow with the toggle, and the body (`data-morph="adv"`). The body
 * is patched IN PLACE between renders (morphNode), never rebuilt: the B3 string it shows changes about every
 * ten seconds while a candidate exists, and a rebuild would reset the register table's scroll position,
 * drop a text selection and lose keyboard focus on the scroll regions.
 */
export function renderAdvanced(vm, ui) {
  const open = !!ui.detailOpen;
  // aria-controls only while the controlled region exists
  const toggle =
    `<button type="button" class="toggle" data-act="toggle-detail" data-fk="toggle-detail" aria-expanded="${open}"${open ? ' aria-controls="adv-body"' : ''}>` +
    `${open ? '▾ Hide technical detail' : '▸ Show technical detail'}</button>`;
  if (!open) {
    return cardOut('', 'idle', [
      eyebrow(7, 'Advanced · raw values', 'code', toggle),
      '<p class="sentence" data-morph="adv">31 registers with pass values, saved-profile comparison, and the raw entity strings.</p>',
    ]);
  }
  const t = buildRegisterTable(vm);
  const mark = { ok: '<span style="color:var(--ok)">✓</span>', bad: '<span style="color:var(--bad)">✗</span>', none: '—' };
  const delta = { eq: '<span style="color:var(--text-3)">=</span>', ne: '<span style="color:var(--warn)">≠</span>', none: '—' };
  const cc = { E1: 'busy', CTX: 'warn', INFO: 'idle' };
  const body = t.rows
    .map(
      (r) =>
        `<tr><td class="mono">${r.reg}</td><td>${esc(r.name)}</td>` +
        `<td><span class="chip ${cc[r.cls]}" title="${esc(CLASS_TIP[r.cls])}">${r.cls}</span></td>` +
        `<td class="num mono">${esc(r.p1)}</td><td class="num mono">${esc(r.p2)}</td><td>${mark[r.match]}</td>` +
        `<td class="num mono">${esc(r.saved)}</td><td>${delta[r.delta]}</td><td class="info">${esc(r.decoded)}</td></tr>`,
    )
    .join('');
  const table =
    `<div class="scrollx" role="region" aria-label="Register values" tabindex="0" data-fk="scroll-regs"><table><thead><tr>` +
    `<th scope="col">Register</th><th scope="col">Name</th><th scope="col">Class</th><th scope="col" class="num">Pass 1</th>` +
    `<th scope="col" class="num">Pass 2</th><th scope="col">Match</th><th scope="col" class="num">${esc(t.savedLabel)}</th>` +
    `<th scope="col">Δ</th><th scope="col">Decoded</th></tr></thead><tbody>${body}</tbody></table></div>` +
    `<div class="caption" data-raw="table-caption">${esc(t.caption)}</div>`;
  const rawRows = RAW_ROWS.map((r) => {
    const v = vm.raw[r.key];
    const id = vm.ids[r.key] || '';
    return (
      `<div class="r"><span class="k">${esc(r.label)}<small>${esc(id)}</small></span>` +
      `<code data-raw="${r.key}">${v === undefined ? '(entity not found)' : esc(v)}</code>` +
      `${pill('copy', `data-act="copy" data-copy-key="${r.key}" data-fk="copy-${r.key}" aria-label="Copy ${esc(r.label)}"`)}</div>`
    );
  }).join('');
  const oblRows = vm.obl
    ? vm.obl
        .map((e) => {
          const c = oblKindClass(e.k);
          const cl = c === 'clear' ? 'ok' : c === 'transient' ? 'warn' : 'bad';
          return `<div class="r"><span class="k">${esc(own(DOMAIN_LABEL, e.d) || e.d)}</span><code>${esc(e.k)} (${esc(own(KIND_TEXT, e.k) || e.k)})</code>${chip(cl, c)}</div>`;
        })
        .join('')
    : `<div class="r"><span class="k">Obligation vector</span><code>${
        vm.oblState === 'invalid'
          ? 'not recognised - see the raw B3 string above'
          : 'none yet - evaluated when a review runs'
      }</code><span></span></div>`;
  const latch = vm.latch.length ? vm.latch.map((d) => own(DOMAIN_LABEL, d) || d).join(', ') : 'none';
  const adv =
    `<div id="adv-body" data-morph="adv">${table}` +
    `<div class="eyebrow" style="margin-top:6px">Raw entity strings</div><div class="raw">${rawRows}</div>` +
    `<div class="eyebrow" style="margin-top:6px">Obligation vector as of the last review</div><div class="raw">${oblRows}</div>` +
    `<div class="raw"><div class="r"><span class="k">Probe latch</span><code>${esc(latch)}${vm.b3 ? ` (${esc(vm.b3.latch)})` : ''}</code><span></span></div></div></div>`;
  return cardOut('', 'idle', [eyebrow(7, 'Advanced · raw values', 'code', toggle), adv]);
}

// ---- card 8: recovery (reserved) ------------------------------------------------------------------
// FB-B2: the one-shot arm is live now (candidate and Saved profile cards), so its ghost tile is gone. Restore stays inert.
export const RECOVERY_TILES = Object.freeze([
  { label: 'Restore Saved Profile', stage: 'FB-E', icon: 'restore', purpose: 'Write the saved profile back to the inverter after a review.' },
  { label: 'Recovery Hold', stage: 'FB-E', icon: 'pause', purpose: 'Hold managed actions while a recovery is unresolved.' },
  { label: 'Validated Resume', stage: 'FB-F', icon: 'play', purpose: 'Acknowledge a recovery and allow managed actions again.' },
]);

export function renderRecovery() {
  const tiles = RECOVERY_TILES.map(
    (t) =>
      `<div class="ghost" role="group" aria-disabled="true" aria-label="${esc(`${t.label}, arrives in ${t.stage}, not available`)}">` +
      `<div class="l">${svg(t.icon)}${esc(t.label)}</div><span class="chip future" style="align-self:flex-start">${esc(t.stage)}</span>` +
      `<div class="p">${esc(t.purpose)}</div></div>`,
  ).join('');
  return cardOut(
    '',
    'future',
    eyebrow(8, 'Recovery', 'restore', '<span class="chip future">Reserved</span>') +
      `<p class="sentence">${esc(SENTENCE.recoveryReserved)}</p><div class="ghosts">${tiles}</div>`,
  );
}

/** Render every card. `ui`: {detailOpen, view, pending, notice, showHeader, title, moreInfoEnabled}. */
export function renderAll(vm, tv, ui, env = makeFormatters()) {
  return {
    header: renderHeader(vm, ui),
    cards: {
      c1: renderProfile(vm, ui, env, tv),
      c2: renderLive(vm, ui, env, tv),
      c3: renderReview(vm, ui, env, tv),
      c4: renderCandidate(vm, ui, env, tv),
      c5: renderChecks(vm, ui, env, tv),
      c6: renderSummary(vm, ui),
      c7: renderAdvanced(vm, ui),
      c8: renderRecovery(),
    },
  };
}

export const CARD_DEFS = Object.freeze([
  { id: 'c1', span: 1, label: 'Saved profile' },
  { id: 'c2', span: 1, label: 'Live match' },
  { id: 'c3', span: 2, label: 'Review current configuration' },
  { id: 'c4', span: 2, label: 'Candidate' },
  { id: 'c5', span: 2, label: 'Save readiness' },
  { id: 'c6', span: 4, label: 'Configuration summary' },
  { id: 'c7', span: 4, label: 'Advanced raw values' },
  { id: 'c8', span: 4, label: 'Recovery' },
]);

export const STYLE = `
:host { display: block; container-type: inline-size; container-name: fbr; color-scheme: dark;
  --card: #0d1728; --card-hi: #111c30; --card-lo: #0b1424;
  --surface: rgba(255,255,255,0.04); --border: rgba(255,255,255,0.08);
  --text: rgba(255,255,255,0.92); --text-2: rgba(255,255,255,0.72); --text-3: rgba(255,255,255,0.46);
  --ok: #55e58e; --warn: #ffbd3d; --bad: #ff6376; --idle: #6d7b91; --busy: #42aaff; --future: #b8adff;
  --sans: "Roboto", "Segoe UI", Arial, sans-serif;
  --mono: "JetBrains Mono", "Cascadia Mono", Consolas, monospace; }
*, *::before, *::after { box-sizing: border-box; }
.root { color: var(--text); font-family: var(--sans); font-size: 14px; line-height: 1.45; }
.root button { font-family: inherit; line-height: inherit; }
.topbar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 16px; margin-bottom: 14px; }
.topbar:empty { display: none; }
.topbar h2 { font-size: 18px; font-weight: 900; margin: 0; letter-spacing: .01em; display: flex; align-items: center; gap: 8px; }
.topbar h2 svg { width: 22px; height: 22px; }
.badges { display: flex; flex-wrap: wrap; gap: 6px; margin-left: auto; }
.badge { display: inline-flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: 999px; font-size: 11px; font-weight: 700; border: 1px solid var(--border); background: var(--surface); color: var(--text-2); }
.badge svg { width: 14px; height: 14px; opacity: .8; }
.badge .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--idle); }
.grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 16px; }
.card { grid-column: span var(--span, 4); min-width: 0; background: linear-gradient(145deg, var(--card-hi), var(--card-lo)); border: 1px solid var(--border); border-radius: 18px; box-shadow: 0 10px 30px rgba(0,0,0,.22); padding: 16px 18px 18px; display: flex; flex-direction: column; gap: 10px; container-type: inline-size; --state: var(--idle); color: var(--text); }
.card.tinted { border-color: color-mix(in srgb, var(--state) 45%, var(--border)); background-image: linear-gradient(145deg, color-mix(in srgb, var(--state) 7%, var(--card-hi)), var(--card-lo)); }
.card.muted { opacity: .8; }
.card[data-act] { cursor: pointer; }
#c8 { min-height: 140px; }
.eyebrow { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 8px; font-size: 10px; font-weight: 800; letter-spacing: .5px; text-transform: uppercase; color: var(--text-3); }
.eyebrow svg { width: 14px; height: 14px; opacity: .8; flex: none; }
.eyebrow .right { margin-left: auto; display: flex; gap: 6px; align-items: center; text-transform: none; letter-spacing: 0; }
.eyebrow .right:empty { display: none; }
.head { display: flex; align-items: center; gap: 10px; min-width: 0; }
.live { display: flex; flex-direction: column; gap: 10px; }
.slot { display: flex; flex-direction: column; gap: 10px; }
.slot:empty { display: none; }
.dot { width: 10px; height: 10px; border-radius: 50%; background: var(--state); flex: none; }
.dot.pulse { animation: pulse 1s ease-in-out infinite; }
.headline { font-size: 22px; font-weight: 900; color: var(--state); text-wrap: balance; line-height: 1.15; min-width: 0; overflow-wrap: anywhere; }
.card.big .headline { font-size: 26px; }
.sentence { font-size: 13px; color: var(--text-2); margin: 0; overflow-wrap: anywhere; }
.rows { display: grid; grid-template-columns: max-content 1fr; gap: 6px 14px; align-items: baseline; }
.rows .k { font-size: 11.5px; font-weight: 700; color: var(--text-3); }
.rows .v { font-size: 14px; font-weight: 600; font-variant-numeric: tabular-nums; min-width: 0; overflow-wrap: anywhere; }
.mono { font-family: var(--mono); font-size: 13px; }
.chiprow { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { display: inline-flex; align-items: center; gap: 4px; padding: 3px 9px; border-radius: 999px; font-size: 10.5px; font-weight: 800; letter-spacing: .3px; text-transform: uppercase; background: color-mix(in srgb, var(--c, var(--idle)) 20%, transparent); color: var(--c, var(--idle)); }
.chip.ok { --c: var(--ok); } .chip.warn { --c: var(--warn); } .chip.bad { --c: var(--bad); } .chip.busy { --c: var(--busy); } .chip.future { --c: var(--future); } .chip.idle { --c: var(--idle); color: #9aa7bb; }
.btn { font-size: 14px; font-weight: 800; padding: 12px 18px; min-height: 44px; border-radius: 12px; border: 1px solid color-mix(in srgb, var(--busy) 55%, var(--border)); background: color-mix(in srgb, var(--busy) 18%, transparent); color: var(--text); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; gap: 8px; }
.btn:hover:not([aria-disabled="true"]) { background: color-mix(in srgb, var(--busy) 28%, transparent); }
.btn[aria-disabled="true"] { opacity: .4; cursor: not-allowed; }
.btn.go { border-color: color-mix(in srgb, var(--ok) 55%, var(--border)); background: color-mix(in srgb, var(--ok) 16%, transparent); }
.btn.go:hover:not([aria-disabled="true"]) { background: color-mix(in srgb, var(--ok) 26%, transparent); }
.btn.quiet { border-color: var(--border); background: transparent; color: var(--text-2); }
.btn svg { width: 18px; height: 18px; }
.caption { font-size: 11.5px; color: var(--text-3); }
.warnnote { color: var(--warn); margin-top: 4px; }
.last { font-size: 12px; color: var(--text-3); border-top: 1px solid var(--border); padding-top: 8px; margin-top: auto; overflow-wrap: anywhere; }
.last b { color: var(--tone, var(--text-2)); font-weight: 700; }
.foot { font-weight: 700; font-size: 13px; } .foot.ok { color: var(--ok); } .foot.warn { color: var(--warn); } .foot.bad { color: var(--bad); }
.footrow { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-top: 4px; }
.sr { position: absolute; width: 1px; height: 1px; margin: -1px; padding: 0; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; border: 0; }

.stepper { display: grid; grid-template-columns: repeat(4, 1fr); gap: 0; position: relative; padding: 4px 0 2px; }
.step { display: flex; flex-direction: column; align-items: center; gap: 6px; font-size: 10.5px; color: var(--text-3); text-align: center; position: relative; }
.step .c { width: 12px; height: 12px; border-radius: 50%; border: 2px solid var(--idle); background: transparent; z-index: 1; }
.step::before { content: ""; position: absolute; top: 5px; left: -50%; width: 100%; height: 2px; background: var(--border); }
.step:first-child::before { display: none; }
.step.on::before { background: var(--sc); }
.step.on .c { border-color: var(--sc); background: var(--sc); }
.step.on { color: var(--sc); }
.step.on.pulse .c { animation: pulse 1s ease-in-out infinite; }
.step.strike { text-decoration: line-through; }
.step.slash .c { background: linear-gradient(135deg, transparent 45%, var(--bad) 45%, var(--bad) 55%, transparent 55%); border-color: var(--bad); }
.step.slash { color: var(--bad); }
.rail-busy .step.on::before { background: linear-gradient(90deg, color-mix(in srgb, var(--busy) 30%, transparent), var(--busy), color-mix(in srgb, var(--busy) 30%, transparent)); background-size: 200% 100%; animation: shimmer 1.4s linear infinite; }
.stepcap { grid-column: 1 / -1; text-align: center; }

.count { display: flex; align-items: center; gap: 10px; }
.count svg { width: 18px; height: 18px; color: var(--cc, var(--text-2)); flex: none; }
.count .n { font-family: var(--mono); font-size: 28px; font-weight: 900; font-variant-numeric: tabular-nums; color: var(--cc, var(--text-2)); }
.count .n.pulse { animation: pulse 1s ease-in-out infinite; }
.bar { height: 3px; border-radius: 2px; background: var(--border); overflow: hidden; }
.bar > i { display: block; height: 100%; width: 100%; background: var(--cc, var(--text-2)); transition: width 1s linear; }

.checks { display: flex; flex-direction: column; gap: 8px; }
.check { display: grid; grid-template-columns: 18px 1fr; gap: 10px; align-items: start; }
.check svg { width: 18px; height: 18px; margin-top: 1px; }
.check .l { font-size: 13px; font-weight: 700; }
.check .d { font-size: 12px; color: var(--text-3); }
.check.pass svg { color: var(--ok); } .check.warn svg { color: var(--warn); } .check.fail svg { color: var(--bad); } .check.unknown svg { color: var(--idle); } .check.pending svg { color: var(--busy); }

.seg { display: inline-flex; gap: 4px; padding: 3px; border-radius: 10px; border: 1px solid var(--border); background: color-mix(in srgb, var(--card) 60%, transparent); }
.seg button { font-size: 12px; font-weight: 700; padding: 7px 10px; min-height: 44px; border: 0; border-radius: 8px; background: transparent; color: var(--text-3); cursor: pointer; display: inline-flex; flex-direction: column; align-items: center; justify-content: center; line-height: 1.15; }
.seg button small { font-size: 9.5px; font-weight: 600; opacity: .85; }
.seg button[aria-pressed="true"] { background: var(--surface); color: var(--text); }
.seg button[aria-disabled="true"] { opacity: .4; cursor: not-allowed; }
.tiles { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; }
.tile { border: 1px solid var(--border); border-radius: 12px; padding: 10px 12px; background: var(--surface); min-width: 0; }
.tile .k { font-size: 10px; font-weight: 800; letter-spacing: .45px; text-transform: uppercase; color: var(--text-3); }
.tile .v { font-size: 15px; font-weight: 700; margin-top: 2px; }
.diff { border-left: 3px solid var(--warn); padding-left: 8px; }
.diff .was { color: var(--warn); font-size: 11px; font-weight: 700; margin-left: 6px; white-space: nowrap; }
table { width: 100%; border-collapse: collapse; font-size: 12.5px; line-height: 1.2; font-variant-numeric: tabular-nums; }
th { font-size: 10.5px; font-weight: 800; letter-spacing: .4px; text-transform: uppercase; color: var(--text-3); text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--border); background: var(--surface); }
td { padding: 7px 8px; border-bottom: 1px solid rgba(255,255,255,.05); vertical-align: top; }
td.num, th.num { text-align: right; }
.scrollx { overflow-x: auto; -webkit-overflow-scrolling: touch; border: 1px solid var(--border); border-radius: 12px; }
.lbl-short { display: none; }
.mode-fold { display: none; }
.legend { font-size: 11px; color: var(--warn); }
.info { font-size: 12px; color: var(--text-3); }
.warnrow, .badrow { display: flex; gap: 8px; align-items: flex-start; font-size: 12.5px; padding: 8px 10px; border-radius: 10px; }
.warnrow { color: var(--warn); border: 1px solid color-mix(in srgb, var(--warn) 40%, var(--border)); background: color-mix(in srgb, var(--warn) 7%, transparent); }
.badrow { color: var(--bad); border: 1px solid color-mix(in srgb, var(--bad) 40%, var(--border)); background: color-mix(in srgb, var(--bad) 7%, transparent); }
.warnrow svg, .badrow svg { width: 16px; height: 16px; flex: none; margin-top: 1px; }

.toggle { font-size: 12px; font-weight: 700; color: var(--text-2); background: var(--surface); border: 1px solid var(--border); border-radius: 999px; padding: 7px 12px; min-height: 44px; cursor: pointer; }
.raw { display: grid; grid-template-columns: 1fr; gap: 6px; }
.raw .r { display: grid; grid-template-columns: 130px 1fr auto; gap: 10px; align-items: start; font-size: 12px; min-width: 0; }
.raw .r .k { color: var(--text-3); font-weight: 700; }
.raw .r .k small { display: block; font-weight: 400; font-size: 10px; font-family: var(--mono); overflow-wrap: anywhere; }
.raw .r code { font-family: var(--mono); font-size: 11.5px; color: var(--text-2); overflow-wrap: anywhere; }
.pill, .copy { min-height: 24px; font-size: 10.5px; font-weight: 700; padding: 3px 8px; border-radius: 999px; border: 1px solid var(--border); background: var(--surface); color: var(--text-3); cursor: pointer; text-transform: none; letter-spacing: 0; }

.ghosts { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
.ghost { border: 1px dashed color-mix(in srgb, var(--future) 40%, var(--border)); border-radius: 12px; padding: 12px; opacity: .45; display: flex; flex-direction: column; gap: 6px; min-height: 96px; pointer-events: none; user-select: none; }
.ghost .l { font-weight: 800; font-size: 13px; display: flex; align-items: center; gap: 6px; }
.ghost .l svg { width: 16px; height: 16px; }
.ghost .p { font-size: 11.5px; color: var(--text-2); }

.sk { display: block; height: 12px; border-radius: 6px; background: rgba(255,255,255,.2); background-image: linear-gradient(90deg, rgba(255,255,255,.2), rgba(255,255,255,.35), rgba(255,255,255,.2)); background-size: 200% 100%; animation: shimmer 1.4s linear infinite; }

button:focus-visible, .scrollx:focus-visible { outline: 2px solid color-mix(in srgb, var(--busy) 60%, transparent); outline-offset: 2px; }

.confirm { display: flex; flex-direction: column; gap: 10px; padding: 12px; border-radius: 12px; border: 1px solid color-mix(in srgb, var(--busy) 45%, var(--border)); background: color-mix(in srgb, var(--busy) 7%, transparent); cursor: default; }
.confirm.inv { border-color: color-mix(in srgb, var(--warn) 45%, var(--border)); background: color-mix(in srgb, var(--warn) 7%, transparent); }
.confirm .checks { gap: 5px; }
.confirm .check { align-items: baseline; }
.confirm .check > div > div { display: inline; }
.confirm .check .d::before { content: " · "; content: " · " / ""; }
.ctitle { font-size: 15px; font-weight: 800; }
.ctitle:focus { outline: none; }
.ctitle:focus-visible { outline: 2px solid color-mix(in srgb, var(--busy) 60%, transparent); outline-offset: 2px; border-radius: 6px; }
.phrase { overflow-wrap: anywhere; }
.armcount { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--text-2); }
.armcount svg { width: 16px; height: 16px; flex: none; }
.armcount [data-t], .armstrip [data-t] { font-family: var(--mono); font-weight: 700; font-variant-numeric: tabular-nums; }
.armstrip { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px 12px; font-size: 12.5px; color: var(--text-2); padding: 8px 10px; border-radius: 10px; border: 1px solid color-mix(in srgb, var(--warn) 40%, var(--border)); cursor: default; }
.armstrip svg { width: 14px; height: 14px; vertical-align: -2px; }
.actblock { display: flex; flex-direction: column; gap: 8px; cursor: default; }
.actres { display: flex; flex-direction: column; gap: 8px; padding: 10px 12px; border-radius: 12px; border: 1px solid color-mix(in srgb, var(--rc, var(--idle)) 45%, var(--border)); background: color-mix(in srgb, var(--rc, var(--idle)) 7%, transparent); cursor: default; }
.actres.ok { --rc: var(--ok); } .actres.warn { --rc: var(--warn); } .actres.bad { --rc: var(--bad); }
.actres .at { font-size: 13px; font-weight: 900; letter-spacing: .02em; color: var(--rc, var(--text)); }
.progress { display: flex; align-items: center; gap: 10px; font-size: 13px; color: var(--text-2); }
.progress:focus { outline: none; }
.head:focus, .actres .at:focus { outline: none; }
.head:focus-visible, .actres .at:focus-visible { outline: 2px solid color-mix(in srgb, var(--busy) 60%, transparent); outline-offset: 2px; border-radius: 6px; }
.spin { width: 16px; height: 16px; flex: none; border-radius: 50%; border: 2px solid color-mix(in srgb, var(--busy) 30%, transparent); border-top-color: var(--busy); animation: spin .9s linear infinite; }

@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .35; } }
@keyframes shimmer { from { background-position: 200% 0; } to { background-position: -200% 0; } }
@keyframes spin { to { transform: rotate(360deg); } }
@media (pointer: coarse) {
  .pill, .copy { min-height: 28px; padding: 5px 11px; }
}
/* Reduced motion: no pulse, no shimmer, no width transition. The universal rule is the safety net for any
   animated element added later; the explicit list names every selector that animates today (a test keeps
   the two in step with the rules above). */
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after { animation: none !important; transition: none !important; }
  .dot.pulse, .step.on.pulse .c, .count .n.pulse, .sk, .rail-busy .step.on::before, .spin { animation: none !important; }
  .bar > i { transition: none; }
  .sk { background-image: none; }
}

@container fbr (max-width: 1100px) {
  .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .card { grid-column: span min(var(--span, 4), 2); }
  #c4, #c5 { grid-column: span 1; }
}
@container fbr (max-width: 700px) {
  .grid { grid-template-columns: 1fr; }
  .card { grid-column: span 1; }
  #c4, #c5 { grid-column: span 1; }
  .card.big .headline { font-size: 22px; }
  #c3 { order: -1; }
}
@container (max-width: 620px) {
  .tiles, .ghosts { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .raw .r { grid-template-columns: 1fr; }
}
@container (min-width: 560px) {
  .confirm .checks { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 5px 18px; }
}
@container (max-width: 420px) {
  td .diff, .tile .diff { display: block; white-space: nowrap; }
  td .diff .was, .tile .diff .was { display: block; margin-left: 0; }
  td, th { padding-left: 6px; padding-right: 6px; }
  .hide-narrow { display: none; }
  .mode-fold { display: block; }
  .lbl-long { display: none; }
  .lbl-short { display: inline; }
}
@supports not (color: color-mix(in srgb, red 50%, blue)) {
  .card.tinted { border-color: rgba(255,255,255,.2); }
  .chip { background: rgba(255,255,255,.1); }
  .btn { background: rgba(66,170,255,.18); border-color: rgba(66,170,255,.5); }
  .btn.go { background: rgba(85,229,142,.16); border-color: rgba(85,229,142,.5); }
  .confirm, .actres { background: rgba(66,170,255,.07); border-color: rgba(255,255,255,.2); }
  .confirm.inv, .actres.warn { background: rgba(255,189,61,.08); border-color: rgba(255,189,61,.4); }
  .warnrow { background: rgba(255,189,61,.08); border-color: rgba(255,189,61,.4); }
  .badrow { background: rgba(255,99,118,.08); border-color: rgba(255,99,118,.4); }
  .seg { background: rgba(13,23,40,.6); }
}
`;

// ===========================================================================
// 7. the custom element
// ===========================================================================
const Base = typeof HTMLElement !== 'undefined' ? HTMLElement : class {};

// FB-B2 (CARD-09): the pass a click listener hands to the guarded actions (arm, Arm Invalidate, Cancel, Save, Invalidate). It is module
// private: not exported, not stored on the element, not readable from a method argument. Only the click listener in _build() holds it,
// and it gives it away only for an event with isTrusted === true (a pointer or key press the browser itself made, not a dispatched one).
// A caller of _act() / _onClick() cannot supply it. This stops script-made clicks; the safety authority is the dongle.
const CLICK_PASS = Object.freeze({ trustedClick: true });

export class EccoFallbackRecoveryCard extends Base {
  constructor() {
    super();
    this._config = null;
    this._hass = null;
    this._fp = null;
    this._vm = null;
    this._anchor = null;
    this._anchorKey = '';
    this._timer = null;
    this._built = false;
    this._connected = false;
    this._cache = {};
    // intent: what the arm was switched on for ('save' | 'invalidate' | null); flow: the Save / Invalidate request this
    // card has sent and not seen answered (see makeFlow / advanceFlow); neither is ever restored from storage
    this._ui = { view: 'auto', localDetail: false, pendingDetail: null, notice: '', intent: null, flow: null };
    this._pendingUntil = 0;
    this._pendingTimer = null;
    this._noticeTimer = null;
    this._armAnchor = null;
    this._armKey = '';
    this._armPendingUntil = 0;
    this._armPendingTimer = null;
    this._cancelUntil = 0;
    this._flowTimer = null;
    this._flowDue = 0;
    this._focusFallback = null;
    this._keys = { review: '', b9: '', arm: '' };
    this._focusKey = null;
    this._focusUntil = 0;
    this._announced = false;
    this._lastReviewKey = '';
    this._env = makeFormatters();
    this._now = () => Date.now();
    this._onVisibility = () => this._visibilityChanged();
    this._root = typeof this.attachShadow === 'function' ? this.attachShadow({ mode: 'open' }) : null;
  }

  static getStubConfig() {
    return {
      type: `custom:${TAG}`,
      entities: {
        profile_state: 'sensor.example_profile_state',
        summary: 'sensor.example_summary',
        review: 'sensor.example_review',
        review_id: 'sensor.example_review_id',
        review_slots: 'sensor.example_review_slots',
        review_context: 'sensor.example_review_context',
        saved_slots: 'sensor.example_saved_slots',
        saved_context: 'sensor.example_saved_context',
        last_result: 'sensor.example_last_result',
        review_button: 'button.example_review_button',
        supervision_stable: 'binary_sensor.example_supervision_stable',
        supervision_state: 'sensor.example_supervision_state',
        ntp_synced: 'binary_sensor.example_ntp_synced',
        write_lock: 'binary_sensor.example_write_lock',
        configuration_online: 'binary_sensor.example_configuration_online',
        arm: 'switch.example_arm',
        free_power_arm: 'switch.example_free_power_arm',
        dump_arm: 'switch.example_dump_arm',
        manual_arm: 'switch.example_manual_arm',
      },
    };
  }

  setConfig(config) {
    this._config = validateConfig(config);
    this._ui.localDetail = readLocalDetail();
    this._ui.view = 'auto';
    this._ui.intent = null;
    this._ui.flow = null;
    this._clearActTimers();
    this._armAnchor = null;
    this._armKey = '';
    this._fp = null;
    this._cache = {};
    this._anchor = null;
    this._anchorKey = '';
    this._build();
    if (this._hass) this._update();
  }

  getCardSize() {
    return 16;
  }

  getGridOptions() {
    return { columns: 'full', rows: 'auto', min_columns: 12, min_rows: 6 };
  }

  get hass() {
    return this._hass;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._config) return;
    const fp = this._fingerprint();
    if (fp === this._fp) return;
    this._fp = fp;
    this._update();
  }

  connectedCallback() {
    this._connected = true;
    if (typeof document !== 'undefined' && document.addEventListener) {
      document.addEventListener('visibilitychange', this._onVisibility);
    }
    if (this._config && this._hass) this._update();
  }

  disconnectedCallback() {
    this._connected = false;
    if (typeof document !== 'undefined' && document.removeEventListener) {
      document.removeEventListener('visibilitychange', this._onVisibility);
    }
    this._stopTimer();
    if (this._pendingTimer) clearTimeout(this._pendingTimer);
    if (this._noticeTimer) clearTimeout(this._noticeTimer);
    this._pendingTimer = null;
    this._noticeTimer = null;
    this._clearActTimers();
  }

  _clearActTimers() {
    if (this._armPendingTimer) clearTimeout(this._armPendingTimer);
    if (this._flowTimer) clearTimeout(this._flowTimer);
    this._armPendingTimer = null;
    this._flowTimer = null;
    this._flowDue = 0;
    this._armPendingUntil = 0;
  }

  // ---- state plumbing ----------------------------------------------------------
  _fingerprint() {
    const ents = this._config.entities;
    const states = (this._hass && this._hass.states) || {};
    const parts = [];
    for (const k of ENTITY_KEYS) {
      const id = ents[k];
      const s = id ? states[id] : undefined;
      parts.push(s ? `${s.state}|${s.last_changed || ''}` : '-');
    }
    const te = this._config.technical_detail_entity;
    parts.push(te && states[te] ? String(states[te].state) : '-');
    const l = this._hass && this._hass.locale;
    parts.push(l ? `${l.language || ''}|${l.time_zone || ''}` : '');
    return parts.join('\u0001');
  }

  _helperState() {
    const te = this._config && this._config.technical_detail_entity;
    const s = te && this._hass && this._hass.states ? this._hass.states[te] : undefined;
    return s && (s.state === 'on' || s.state === 'off') ? s.state : null;
  }

  _detailOpen() {
    const helper = this._helperState();
    const pd = this._ui.pendingDetail;
    if (helper !== null && pd && this._now() < pd.until) return pd.value;
    return resolveDetail({ helperState: helper, local: this._ui.localDetail });
  }

  _update() {
    if (!this._config) return;
    const now = this._now();
    const { E, changed } = readEntities(this._config.entities, this._hass && this._hass.states);
    const vm = deriveModel(E, this._config.entities);
    const reviewKey = `${E.review}|${changed.review}`;
    const keys = { review: reviewKey, b9: `${E.last_result}|${changed.last_result}`, arm: `${E.arm}|${changed.arm}` };
    if (reviewKey !== this._lastReviewKey) {
      this._lastReviewKey = reviewKey;
      this._pendingUntil = 0; // the firmware answered; the press debounce is over
    }
    if (vm.hasCand && vm.exp !== null) {
      if (reviewKey !== this._anchorKey) {
        this._anchor = makeAnchor({ exp: vm.exp, lastChangedMs: changed.review, receivedMs: now, nowMs: now });
        this._anchorKey = reviewKey;
      }
    } else {
      this._anchor = null;
      this._anchorKey = '';
      this._announced = false;
    }
    // the arm countdown starts when Home Assistant reports the switch on; the intent (what it was armed for) ends with the arm
    if (vm.arm.state === true) {
      if (keys.arm !== this._armKey || !this._armAnchor) {
        this._armAnchor = makeAnchor({ exp: ARM_TTL_S, lastChangedMs: changed.arm, receivedMs: now, nowMs: now });
        this._armKey = keys.arm;
      }
      this._armPendingUntil = 0;
    } else {
      this._armAnchor = null;
      this._armKey = '';
      this._cancelUntil = 0;
      if (vm.arm.state === false && now >= this._armPendingUntil) this._ui.intent = null;
    }
    // the request state: answered, running, timed out or still waiting. FB-B2 (CARD-06): evaluated on EVERY update (and so on
    // connectedCallback too), not only by the one-shot timer, so a card that was detached and attached again cannot keep a request pending for ever
    this._keys = keys;
    this._vm = vm;
    this._advanceFlow();
    this._ui.pendingDetail = this._helperState() === null ? null : this._ui.pendingDetail;
    const h = this._hass;
    this._env = makeFormatters({
      locale: (h && h.locale && h.locale.language) || (h && h.language) || undefined,
      timeZone: h && h.locale && h.locale.time_zone === 'server' && h.config ? h.config.time_zone : undefined,
    });
    this._vm = vm;
    this._renderCards();
    this._ensureTimer();
  }

  // ---- the request state of a Save / Invalidate this card sent --------------------------------------------------------
  /** Advance the request against the live model; hand the keyboard focus on when the progress row that had it goes away (CARD-12). */
  _advanceFlow() {
    const vm = this._vm;
    const was = flowPendingKind(this._ui.flow);
    const hadFocus = !!was && this._focusedKey() === 'flow-status';
    this._ui.flow = advanceFlow(this._ui.flow, {
      review: vm ? vm.review : null,
      b9Key: this._keys.b9,
      armState: vm ? vm.arm.state : null,
      nowMs: this._now(),
    });
    // the progress row is replaced by the outcome (or the "no result yet" message): focus follows to the result heading, never to a button
    if (hadFocus && !flowPendingKind(this._ui.flow)) this._focusOn(was === 'invalidate' ? 'act-result-inv' : 'act-result', was === 'invalidate' ? 'c1-head' : null);
    this._syncFlowTimer();
  }

  /**
   * One timer for the next moment the request state can change by itself: the end of the 30 s window, or - when the arm is already
   * seen off - the end of the arm-off grace. (Re)armed from the request's own send time on every update, so a detach / attach cannot lose it.
   */
  _syncFlowTimer(force = false) {
    const f = this._ui.flow;
    if (!f || f.state !== 'sent') {
      if (this._flowTimer) clearTimeout(this._flowTimer);
      this._flowTimer = null;
      this._flowDue = 0;
      return;
    }
    if (!force && !this._connected && !this._flowTimer) return;
    let due = f.atMs + ACT_PENDING_TIMEOUT_MS;
    if (f.armOn && this._vm && this._vm.arm.state === false) due = Math.min(due, f.atMs + ARM_OFF_GRACE_MS);
    if (this._flowTimer && this._flowDue === due) return;
    if (this._flowTimer) clearTimeout(this._flowTimer);
    this._flowDue = due;
    this._flowTimer = setTimeout(() => {
      this._flowTimer = null;
      this._advanceFlow();
      this._renderCards();
    }, Math.max(0, due - this._now()) + 50);
  }

  // ---- DOM ---------------------------------------------------------------------------
  _build() {
    if (!this._root || this._built) return;
    const cards = CARD_DEFS.map(
      (c) => `<section class="card" id="${c.id}" style="--span:${c.span}" aria-label="${esc(c.label)}"></section>`,
    ).join('');
    this._root.innerHTML =
      `<style>${STYLE}</style><div class="root"><div id="top"></div><div class="grid" id="grid">${cards}</div>` +
      `<div class="sr" id="announce" role="status" aria-live="polite" aria-atomic="true"></div></div>`;
    this._root.addEventListener('click', (e) => this._onClick(e, e && e.isTrusted === true ? CLICK_PASS : null));
    this._built = true;
  }

  _uiState() {
    const now = this._now();
    return {
      detailOpen: this._detailOpen(),
      view: this._ui.view,
      pending: now < this._pendingUntil,
      notice: this._ui.notice,
      showHeader: this._config.show_header,
      title: this._config.title,
      moreInfoEnabled: true,
      intent: this._ui.intent,
      flow: this._ui.flow,
      armPending: now < this._armPendingUntil,
      cancelling: now < this._cancelUntil,
    };
  }

  _renderCards() {
    if (!this._vm || !this._config) return;
    const tv = this._timeViewNow();
    const out = renderAll(this._vm, tv, this._uiState(), this._env);
    this._lastRender = out;
    if (!this._root) return;
    this._patchTop(out.header);
    for (const def of CARD_DEFS) this._patchCard(def.id, out.cards[def.id]);
    this._applyTime(tv);
    this._announceIfNeeded(tv);
    this._applyFocus();
  }

  _timeViewNow() {
    return timeView(this._anchor, this._now(), this._armAnchor);
  }

  /** Ask for keyboard focus on the element with this data-fk once it exists (after the click's result is rendered). */
  _focusOn(key, fallback = null) {
    this._focusKey = key;
    this._focusFallback = fallback; // used only when the first key is not on screen at the moment the focus is applied
    this._focusUntil = this._now() + 8000;
  }

  /** The data-fk of the element that holds the focus inside the card, or null. */
  _focusedKey() {
    const a = this._root && this._root.activeElement;
    return a && typeof a.getAttribute === 'function' ? a.getAttribute('data-fk') : null;
  }

  _applyFocus() {
    if (!this._focusKey || !this._root || typeof this._root.querySelector !== 'function') return;
    if (this._now() > this._focusUntil) {
      this._focusKey = null;
      return;
    }
    let el = this._root.querySelector(`[data-fk="${this._focusKey}"]`);
    if (!el && this._focusFallback) el = this._root.querySelector(`[data-fk="${this._focusFallback}"]`);
    if (el && typeof el.focus === 'function') {
      el.focus();
      this._focusKey = null;
      this._focusFallback = null;
    }
  }

  _patchTop(html) {
    const el = this._root.getElementById ? this._root.getElementById('top') : null;
    if (!el || this._cache.top === html) return;
    this._cache.top = html;
    el.innerHTML = html;
  }

  _patchCard(id, c) {
    const el = this._root.getElementById ? this._root.getElementById(id) : null;
    if (!el) return;
    const key = `${c.cls}|${c.state}|${JSON.stringify(c.attrs)}`;
    const prev = this._cache[id] || { key: '', html: null, kids: null };
    if (prev.key !== key) {
      el.className = `card ${c.cls}`.trim();
      el.style.setProperty('--state', c.state);
      for (const a of ['data-act', 'data-ent']) {
        if (c.attrs[a] === undefined) el.removeAttribute(a);
        else el.setAttribute(a, c.attrs[a]);
      }
    }
    if (prev.html !== c.inner) this._apply(el, prev, c);
    this._cache[id] = { key, html: c.inner, kids: c.kids };
  }

  /**
   * Replace only what changed. A persistent `data-live` kid keeps its element
   * (the text change is announced); the focused control is re-focused by its
   * data-fk when its element had to be replaced.
   */
  _apply(el, prev, c) {
    const doc = el.ownerDocument;
    const root = this._root;
    const active = root && root.activeElement && el.contains(root.activeElement) ? root.activeElement : null;
    const fk = active && active.getAttribute ? active.getAttribute('data-fk') : null;
    const plan = c.kids ? planPatch(prev.kids, c.kids) : null;
    const old = plan ? Array.from(el.children) : [];
    if (!plan || old.length !== plan.length) {
      el.innerHTML = c.inner;
    } else {
      plan.forEach((op, i) => {
        if (op === 'keep') return;
        const tpl = doc.createElement('template');
        tpl.innerHTML = c.kids[i];
        const nk = tpl.content.firstElementChild;
        if (op === 'live') {
          old[i].innerHTML = nk.innerHTML;
          const style = nk.getAttribute('style');
          if (style === null) old[i].removeAttribute('style');
          else old[i].setAttribute('style', style);
        } else if (op === 'morph') morphNode(old[i], nk);
        else old[i].replaceWith(nk);
      });
    }
    if (fk) {
      const again = el.querySelector(`[data-fk="${fk}"]`);
      if (again && again !== active && typeof again.focus === 'function') again.focus({ preventScroll: true });
    }
  }

  _applyTime(tv) {
    if (!this._root || !this._root.querySelectorAll) return;
    const texts = timeTexts(tv);
    this._root.querySelectorAll('[data-t]').forEach((n) => {
      const t = texts[n.getAttribute('data-t')];
      if (t !== undefined && n.textContent !== t) n.textContent = t;
    });
    this._root.querySelectorAll('[data-tw]').forEach((n) => {
      const w = `${tv.pct.toFixed(2)}%`;
      if (n.style.width === w) return;
      // the first paint and a firmware resync that makes the bar LONGER snap without animation;
      // the normal one-second shrink keeps its linear transition
      const snap = !n.dataset.set || parseFloat(w) > parseFloat(n.style.width);
      if (snap) n.style.transition = 'none';
      n.style.width = w;
      if (snap) {
        void n.offsetWidth;
        n.style.transition = '';
        n.dataset.set = '1';
      }
    });
  }

  _announceIfNeeded(tv) {
    if (!tv.has || this._announced) return;
    if (tv.rem !== null && tv.rem > 0 && tv.rem <= URGENT_S) {
      this._announced = true;
      this._announce(`Candidate expires in ${tv.rem} seconds`);
    }
  }

  _announce(msg) {
    const el = this._root && this._root.getElementById ? this._root.getElementById('announce') : null;
    if (el) el.textContent = msg;
    this._lastAnnouncement = msg;
  }

  // ---- ticking (only while a candidate is on screen) -------------------------------
  _ensureTimer() {
    const hidden = typeof document !== 'undefined' && document.hidden === true;
    const now = this._now();
    const stale = this._anchor && now - this._anchor.at > STALE_ANCHOR_S * 1000;
    // an arm that is still reported on long after its 120 s limit is waiting for the dongle: stop counting
    const armStale = this._armAnchor && now - this._armAnchor.at > (ARM_TTL_S + 60) * 1000;
    const needed = ((!!this._anchor && !stale) || (!!this._armAnchor && !armStale)) && this._connected && !hidden;
    if (needed && !this._timer) this._timer = setInterval(() => this._tick(), TICK_MS);
    else if (!needed && this._timer) this._stopTimer();
  }

  _stopTimer() {
    if (this._timer) clearInterval(this._timer);
    this._timer = null;
  }

  _tick() {
    if (!this._anchor && !this._armAnchor) {
      this._stopTimer();
      return;
    }
    this._renderCards();
    this._ensureTimer();
  }

  _visibilityChanged() {
    if (typeof document !== 'undefined' && document.hidden) this._stopTimer();
    else {
      this._renderCards();
      this._ensureTimer();
    }
  }

  // ---- actions --------------------------------------------------------------------------
  _onClick(e, pass = null) {
    const target = e.target && e.target.closest ? e.target.closest('[data-act]') : null;
    if (!target) return;
    const act = target.getAttribute('data-act');
    // a click that ends a text selection is not a tap on the card
    if (target.tagName === 'SECTION') {
      try {
        const sel = this._root.getSelection ? this._root.getSelection() : window.getSelection();
        if (sel && String(sel).length > 0) return;
      } catch (err) {
        /* ignore */
      }
    }
    return this._act(act, {
      view: target.getAttribute('data-view'),
      copyKey: target.getAttribute('data-copy-key'),
      ent: target.getAttribute('data-ent'),
      id: target.getAttribute('data-id'),
      variant: target.getAttribute('data-variant'),
      // the pass the listener gave this click (null for an event the browser did not make); see CLICK_PASS
      pass,
    });
  }

  /** Every operator action goes through here (and nowhere else). */
  _act(name, ds = {}) {
    switch (name) {
      case 'review':
        return this._pressReview();
      case 'toggle-detail':
        return this._toggleDetail();
      case 'view':
        if (ds.view === 'cand' || ds.view === 'saved') {
          const ok = ds.view === 'cand' ? this._vm && this._vm.candOK : this._vm && this._vm.savedOK;
          if (ok) {
            this._ui.view = ds.view;
            this._renderCards();
          }
        }
        return null;
      case 'copy':
        return this._copy(ds.copyKey);
      case 'more-info':
        return this._moreInfo(ds.ent);
      case 'goto-summary':
        return this._gotoSummary();
      case 'arm':
        return this._trusted(ds, () => this._pressArm('save'));
      case 'arm-invalidate':
        return this._trusted(ds, () => this._pressArm('invalidate'));
      case 'arm-cancel':
        return this._trusted(ds, () => this._cancelArm());
      case 'save':
        return this._trusted(ds, () => this._pressSave(ds));
      case 'invalidate':
        return this._trusted(ds, () => this._pressInvalidate(ds));
      default: // includes 'stay' (a panel that only keeps the card's own tap from firing) and every unknown name
        return null;
    }
  }

  /** The guard of every action that writes: only a click that carries the listener's pass (a trusted user click) gets through. */
  _trusted(ds, fn) {
    if (ds.pass !== CLICK_PASS) return { sent: false, why: FLOW_TEXT.notAUserClick };
    return fn();
  }

  _call(call, onRejected = null) {
    if (!isAllowedServiceCall(call, this._config)) throw new Error(`${TAG}: service call not allowed`);
    if (!this._hass || typeof this._hass.callService !== 'function') {
      this._setNotice('Home Assistant is not connected. Try again.');
      return false;
    }
    let result;
    try {
      result = this._hass.callService(call.domain, call.service, call.data);
    } catch (err) {
      this._setNotice('Home Assistant did not accept the request. Check the connection and try again.');
      return false;
    }
    if (result && typeof result.catch === 'function') {
      result.catch(() => {
        this._setNotice('Home Assistant did not accept the request. Check the connection and try again.');
        if (onRejected) onRejected();
      });
    }
    return true;
  }

  _pressReview() {
    if (!this._vm || !this._config) return { sent: false, why: 'not ready' };
    const bs = reviewButtonState(this._vm, { pending: this._now() < this._pendingUntil, act: flowPendingKind(this._ui.flow) });
    if (bs.disabled) return { sent: false, why: bs.why };
    const sent = this._call(buildServiceCall('review', this._config));
    if (sent) {
      // FB-B2 (CARD-04): a Review press does NOT end an unanswered Save / Invalidate request (a timed-out or rejected one included): only
      // the dongle's answer does (B3 leaves what it was, or B9 changes). Review turns the arm off and replaces the candidate, so that answer follows.
      if (this._ui.intent !== 'sent') this._ui.intent = null; // a spent arm stays spent (the echo of the arm turning off clears it)
      this._pendingUntil = this._now() + 1500;
      if (this._pendingTimer) clearTimeout(this._pendingTimer);
      this._pendingTimer = setTimeout(() => {
        this._pendingUntil = 0;
        this._renderCards();
      }, 1600);
      this._renderCards();
    }
    return { sent };
  }

  /** Switch the arm on for `kind` ('save' | 'invalidate'). Never optimistic: the confirmation panel waits for the switch to report on. */
  _pressArm(kind) {
    if (!this._vm || !this._config) return { sent: false, why: 'not ready' };
    const tv = this._timeViewNow();
    const pending = !!flowPendingKind(this._ui.flow);
    const gate = kind === 'invalidate' ? invalidateGate(this._vm, tv, { pending }) : saveGate(this._vm, tv, { pending });
    const bs = armButtonState(gate, this._vm, { pending: this._now() < this._armPendingUntil, kind, cancelling: this._now() < this._cancelUntil });
    if (bs.disabled) return { sent: false, why: bs.why };
    this._ui.intent = kind;
    this._ui.flow = null;
    const sent = this._call(buildServiceCall('arm_on', this._config));
    if (!sent) {
      this._ui.intent = null;
      return { sent: false, why: 'not sent' };
    }
    this._armPendingUntil = this._now() + ARM_PENDING_MS;
    if (this._armPendingTimer) clearTimeout(this._armPendingTimer);
    this._armPendingTimer = setTimeout(() => {
      this._armPendingTimer = null;
      this._armPendingUntil = 0;
      if (this._vm && this._vm.arm.state !== true) {
        this._ui.intent = null;
        this._setNotice(FLOW_TEXT.armNoEcho);
      } else this._renderCards();
    }, ARM_PENDING_MS + 50);
    this._focusOn(kind === 'invalidate' ? 'confirm-inv-title' : 'confirm-save-title');
    this._renderCards();
    return { sent: true };
  }

  /** Turn the arm off again (the safe direction), from the panel's Cancel or the arm strip. */
  _cancelArm() {
    if (!this._vm || !this._config) return { sent: false, why: 'not ready' };
    if (!this._vm.arm.configured) return { sent: false, why: FLOW_TEXT.notSetUp };
    if (this._vm.arm.state !== true) return { sent: false, why: 'The arm is not on' };
    const kind = this._ui.intent;
    const sent = this._call(buildServiceCall('arm_off', this._config));
    if (sent) {
      this._ui.intent = null;
      this._cancelUntil = this._now() + ARM_PENDING_MS; // until Home Assistant reports it off, no confirm is offered
      this._focusOn(kind === 'invalidate' ? 'arm-invalidate' : 'arm');
      this._renderCards();
    }
    return { sent };
  }

  /**
   * Send the save. Everything is re-checked HERE, from the live model: the disabled look of a button is never the
   * guard. The request carries exactly the candidate ID that is on screen (the button carries the ID it was drawn
   * with; a different current ID means the screen is stale and nothing is sent) and the phrase built from it.
   * There is no retry: a refused or unanswered request is shown, and the operator reviews again.
   */
  _pressSave(ds) {
    const vm = this._vm;
    if (!vm || !this._config) return { sent: false, why: 'not ready' };
    if (flowPendingKind(this._ui.flow)) return { sent: false, why: FLOW_TEXT.inFlight };
    if (this._ui.intent === 'invalidate') return { sent: false, why: FLOW_TEXT.armForInvalidate };
    const gate = saveGate(vm, this._timeViewNow(), { pending: false, cancelling: this._now() < this._cancelUntil });
    if (!gate.allowed) return { sent: false, why: gate.why };
    // FB-B2 (CARD-08): only the arm THIS card switched on for a save confirms a save (an arm on for any other reason has no panel)
    if (this._ui.intent !== 'save') return { sent: false, why: this._ui.intent === 'sent' ? FLOW_TEXT.armSpentWhy : FLOW_TEXT.armElsewhereWhy };
    if (typeof ds.id !== 'string' || ds.id === '') return { sent: false, why: FLOW_TEXT.noConfirmId };
    if (ds.id !== vm.reviewId || (ds.variant || 'save') !== gate.variant) {
      this._setNotice(FLOW_TEXT.changedOnScreen);
      return { sent: false, why: FLOW_TEXT.changedOnScreen };
    }
    const kind = gate.variant === 'replace_corrupt' ? 'replace_corrupt' : 'save';
    const flow = makeFlow('save', { id: vm.reviewId, variant: gate.variant, effect: gate.effect, vm, nowMs: this._now(), keys: this._keys });
    const sent = this._call(buildServiceCall(kind, this._config, { id: vm.reviewId }), () => this._flowNotAccepted(flow));
    if (!sent) return { sent: false, why: 'not sent' };
    // FB-B2 (CARD-04): every attempt uses the arm up (the dongle turns it off, even when it refuses). The confirmation of this arm episode
    // is over: it cannot come back after a timeout or a rejected call; a new episode needs a new Arm click (and the arm off first).
    this._ui.intent = 'sent';
    this._flowSent(flow);
    return { sent: true };
  }

  /** Send the invalidate for the stored profile's full 16-hex binding (B2 id), the same way. */
  _pressInvalidate(ds) {
    const vm = this._vm;
    if (!vm || !this._config) return { sent: false, why: 'not ready' };
    if (flowPendingKind(this._ui.flow)) return { sent: false, why: FLOW_TEXT.inFlight };
    const gate = invalidateGate(vm, this._timeViewNow(), { pending: false, cancelling: this._now() < this._cancelUntil });
    if (!gate.allowed) return { sent: false, why: gate.why };
    // FB-B2 (CARD-08): only the arm THIS card switched on for an invalidate confirms an invalidate
    if (this._ui.intent !== 'invalidate') return { sent: false, why: this._ui.intent === 'sent' ? FLOW_TEXT.armSpentWhy : FLOW_TEXT.armElsewhereWhy };
    if (typeof ds.id !== 'string' || ds.id === '') return { sent: false, why: FLOW_TEXT.noConfirmId };
    if (ds.id !== vm.idHex) {
      this._setNotice(FLOW_TEXT.changedOnScreen);
      return { sent: false, why: FLOW_TEXT.changedOnScreen };
    }
    const flow = makeFlow('invalidate', { id: vm.idHex, vm, nowMs: this._now(), keys: this._keys });
    const sent = this._call(buildServiceCall('invalidate', this._config, { id: vm.idHex }), () => this._flowNotAccepted(flow));
    if (!sent) return { sent: false, why: 'not sent' };
    this._ui.intent = 'sent'; // FB-B2 (CARD-04): the attempt uses the arm up, as for a save
    this._flowSent(flow);
    return { sent: true };
  }

  _flowSent(flow) {
    this._ui.flow = flow;
    this._syncFlowTimer(true);
    this._focusOn('flow-status');
    this._renderCards();
  }

  /** Home Assistant rejected the call: it may not have reached the dongle, so the request stays "unanswered", never retried. */
  _flowNotAccepted(flow) {
    if (this._ui.flow === flow) {
      this._ui.flow = { ...flow, state: 'unsure' };
      this._renderCards();
    }
  }

  _toggleDetail() {
    const next = !this._detailOpen();
    if (this._helperState() !== null) {
      this._ui.pendingDetail = { value: next, until: this._now() + 2500 };
      const sent = this._call(buildServiceCall('detail_toggle', this._config));
      this._renderCards();
      return { sent, helper: true };
    }
    this._ui.localDetail = next;
    writeLocalDetail(next);
    this._renderCards();
    return { sent: false, helper: false };
  }

  _setNotice(msg) {
    this._ui.notice = msg;
    if (this._noticeTimer) clearTimeout(this._noticeTimer);
    this._noticeTimer = setTimeout(() => {
      this._ui.notice = '';
      this._renderCards();
    }, 8000);
    this._renderCards();
  }

  _moreInfo(key) {
    const id = this._config && this._config.entities[key];
    if (!id || typeof this.dispatchEvent !== 'function' || typeof CustomEvent === 'undefined') return false;
    this.dispatchEvent(new CustomEvent('hass-more-info', { detail: { entityId: id }, bubbles: true, composed: true }));
    return true;
  }

  _gotoSummary() {
    if (this._vm && this._vm.candOK) this._ui.view = 'cand';
    this._renderCards();
    const el = this._root && this._root.getElementById ? this._root.getElementById('c6') : null;
    if (el && el.scrollIntoView) {
      const reduce =
        typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
      el.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
    }
    return true;
  }

  _copyText(key) {
    if (!this._vm) return null;
    if (key === 'id') return this._vm.reviewId;
    const v = this._vm.raw[key];
    return typeof v === 'string' ? v : null;
  }

  async _copy(key) {
    const text = this._copyText(key);
    if (text === null || text === undefined) return 'nothing';
    const res = await copyToClipboard(text);
    const btn = this._root && this._root.querySelector ? this._root.querySelector(`[data-copy-key="${key}"]`) : null;
    if (btn) {
      const label = btn.textContent;
      btn.textContent = res === 'copied' ? 'copied' : 'select + copy';
      if (res !== 'copied') this._selectCode(key);
      setTimeout(() => {
        btn.textContent = label;
      }, 1400);
    }
    return res;
  }

  _selectCode(key) {
    try {
      const code = this._root.querySelector(`[data-raw="${key}"]`);
      if (!code) return;
      const range = document.createRange();
      range.selectNodeContents(code);
      const sel = this._root.getSelection ? this._root.getSelection() : window.getSelection();
      sel.removeAllRanges();
      sel.addRange(range);
    } catch (err) {
      /* selection is a best-effort fallback */
    }
  }
}

// The only import-time side effect: register the element and the card picker entry.
if (typeof customElements !== 'undefined' && typeof HTMLElement !== 'undefined') {
  if (!customElements.get(TAG)) customElements.define(TAG, EccoFallbackRecoveryCard);
  if (typeof window !== 'undefined') {
    window.customCards = window.customCards || [];
    if (!window.customCards.some((c) => c && c.type === TAG)) {
      window.customCards.push({
        type: TAG,
        name: 'ECCO Fallback / Recovery Card',
        description:
          'Review of the inverter fallback-profile registers (saved profile, live match, candidate with a countdown, save readiness, raw values) and the guarded save / invalidate of the saved profile.',
        preview: false,
      });
    }
  }
}
