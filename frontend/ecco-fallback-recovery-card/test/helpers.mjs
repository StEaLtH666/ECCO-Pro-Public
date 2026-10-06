// Shared helpers for the node tests (not a test file itself: the test glob is test/*.test.mjs).
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

export const here = path.dirname(fileURLToPath(import.meta.url));
export const cardDir = path.resolve(here, '..');
export const repoRoot = path.resolve(cardDir, '..', '..');

export const card = await import('../ecco-fallback-recovery-card.js');

export const scenarios = JSON.parse(readFileSync(path.join(here, 'fixtures', 'scenarios.json'), 'utf8'));
export const meta = JSON.parse(readFileSync(path.join(here, 'fixtures', 'scenario_meta.json'), 'utf8'));

/** Placeholder ids only: the real ids live in the dashboard YAML. */
export const IDS = Object.freeze({
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
  // FB-B2: the arm switch (the card switches it from a user click) and the three read-only write arms
  arm: 'switch.example_arm',
  free_power_arm: 'switch.example_free_power_arm',
  dump_arm: 'switch.example_dump_arm',
  manual_arm: 'switch.example_manual_arm',
});

export const T0 = 1_800_000_000_000;
export const fmt = card.makeFormatters({ locale: 'en-GB', timeZone: 'UTC' });

export function uiDefaults(over = {}) {
  return {
    detailOpen: true,
    view: 'auto',
    pending: false,
    notice: '',
    showHeader: true,
    title: card.DEFAULT_TITLE,
    moreInfoEnabled: true,
    ...over,
  };
}

/**
 * Derive + anchor + time view for a named scenario, `elapsedS` seconds after the firmware publish. `armOnS` (seconds
 * after the publish at which Home Assistant reported the arm on) gives the arm countdown an anchor; without it the
 * arm view has no countdown.
 */
export function build(name, { elapsedS = 0, E = null, armOnS = null, ids = IDS } = {}) {
  const states = E || scenarios[name];
  if (!states) throw new Error(`unknown scenario ${name}`);
  const vm = card.deriveModel(states, ids);
  const anchor = vm.hasCand && vm.exp !== null ? card.makeAnchor({ exp: vm.exp, lastChangedMs: T0, nowMs: T0 }) : null;
  const now = T0 + elapsedS * 1000;
  const armAnchor = armOnS === null ? null : card.makeAnchor({ exp: card.ARM_TTL_S, lastChangedMs: T0 + armOnS * 1000, nowMs: now });
  const tv = card.timeView(anchor, now, armAnchor);
  return { vm, anchor, armAnchor, tv };
}

export function renderScenario(name, { elapsedS = 0, ui = {}, E = null, armOnS = null, ids = IDS } = {}) {
  const { vm, tv } = build(name, { elapsedS, E, armOnS, ids });
  return { vm, tv, out: card.renderAll(vm, tv, uiDefaults(ui), fmt) };
}

const ENT = { '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#39;': "'" };

/** The visible text nodes of an HTML string, with the time placeholders filled. */
export function textNodes(html, tv) {
  const filled = (tv ? card.fillTime(html, tv) : html).replace(/<span[^>]*\sdata-t="\w+"[^>]*>([^<]*)<\/span>/g, '$1');
  const out = [];
  const re = />([^<>]+)</g;
  let m;
  while ((m = re.exec(`>${filled}<`)) !== null) {
    const t = m[1].replace(/&(amp|lt|gt|quot|#39);/g, (e) => ENT[e]).trim();
    if (t) out.push(t);
  }
  return out;
}

export function allText(out, tv) {
  const parts = [out.header, ...Object.values(out.cards).map((c) => c.inner)];
  return parts.flatMap((h) => textNodes(h, tv));
}

// ---- a strict mock `hass` ------------------------------------------------------------------------
// The card may touch exactly these members of Home Assistant's hass object. Any other member (callWS, callApi,
// sendMessage, connection, ...) throws on access and is recorded, so a second write path cannot hide behind a
// mock that simply lacks the member.
export const HASS_ALLOWED = Object.freeze(['states', 'locale', 'config', 'language', 'callService']);
const CALLS = new WeakMap();
const TOUCHED = new WeakMap();

export function strictHass(raw, calls = [], touched = []) {
  const deny = (k) => {
    touched.push(String(k));
    throw new Error(`the card touched hass.${String(k)}, which it must never use`);
  };
  const proxy = new Proxy(raw, {
    get(t, k) {
      if (typeof k === 'symbol') return t[k];
      if (!HASS_ALLOWED.includes(k)) deny(k);
      return t[k];
    },
    has(t, k) {
      if (typeof k !== 'symbol' && !HASS_ALLOWED.includes(k)) deny(k);
      return k in t;
    },
    set(t, k, v) {
      if (k !== 'callService') deny(k);
      t[k] = v;
      return true;
    },
  });
  CALLS.set(proxy, calls);
  TOUCHED.set(proxy, touched);
  return proxy;
}

/** The service calls a strict hass has received (tests read them here, outside the proxy). */
export const callsOf = (h) => CALLS.get(h);
/** Every hass member the card touched outside the allowed set (also thrown at the time). */
export const touchedOf = (h) => TOUCHED.get(h);

/**
 * The hass.states map for the entity state map `E`, all published at `changedMs`; `stamps` gives single entities
 * (by config key) their own last_changed, e.g. the moment the arm switch turned on.
 */
export function statesFor(E, changedMs = T0, helper = null, stamps = {}) {
  const states = {};
  const stamp = new Date(changedMs).toISOString();
  for (const [k, id] of Object.entries(IDS)) {
    if (E[k] === undefined) continue;
    const own = stamps[k] === undefined ? stamp : new Date(stamps[k]).toISOString();
    states[id] = { entity_id: id, state: E[k], last_changed: own };
  }
  if (helper) states[helper.id] = { entity_id: helper.id, state: helper.state, last_changed: stamp };
  return states;
}

/** A strict hass for the entity state map `E` (config key -> state string), all published at `changedMs`. */
export function hassFor(E, changedMs = T0, helper = null, stamps = {}) {
  return withStates(
    strictHass({
      states: {},
      locale: { language: 'en-GB', time_zone: 'UTC' },
      config: { time_zone: 'UTC' },
    }),
    statesFor(E, changedMs, helper, stamps),
  );
}

/** A new strict hass with the given state map that shares the call log of `h` (hass objects are replaced, not mutated, by HA). */
export function withStates(h, states) {
  const calls = CALLS.get(h) || [];
  const touched = TOUCHED.get(h) || [];
  const raw = {
    states,
    locale: h.locale,
    config: h.config,
    callService(domain, service, data) {
      calls.push({ domain, service, data });
      return Promise.resolve();
    },
  };
  return strictHass(raw, calls, touched);
}

/** Every regex literal the Energy Actions card uses with .test( (same extraction as the FB-C1 suite). */
export function cardRegexes() {
  const src = path.join(repoRoot, 'frontend', 'ecco-energy-actions-card', 'src');
  if (!existsSync(src)) throw new Error(`energy actions card source not found at ${src}`);
  const files = [];
  for (const f of readdirSync(src).sort()) if (f.endsWith('.ts')) files.push(path.join(src, f));
  const util = path.join(src, 'utils');
  if (existsSync(util)) for (const f of readdirSync(util).sort()) if (f.endsWith('.ts')) files.push(path.join(util, f));
  const out = [];
  const seen = new Set();
  for (const f of files) {
    const text = readFileSync(f, 'utf8');
    const a = /const\s+\w+\s*=\s*\/((?:\\.|[^/\n\\])+)\/([a-z]*)\s*;/g;
    const b = /(?<![\w/])\/((?:\\.|[^/\n\\])+)\/([a-z]*)\.test\(/g;
    for (const re of [a, b]) {
      let m;
      while ((m = re.exec(text)) !== null) {
        const key = `${m[1]}/${m[2]}`;
        if (seen.has(key)) continue;
        seen.add(key);
        out.push({ source: path.basename(f), re: new RegExp(m[1], m[2]) });
      }
    }
  }
  return out;
}

/** The hazard phrases of the design (S5 8.2) restated independently of the TS parse. */
const F = ['FAI', 'LED'].join('');
const D = ['DEFER', 'RED'].join('');
export const HAZARD_PATTERNS = [
  /RECOVERY REQUIRED/i,
  /OPERATOR DECISION REQUIRED/i,
  /RESTORE BLOCKED/i,
  /RECOVERY BLOCKED/i,
  new RegExp(`\\b${F}\\b`, 'i'),
  /VERIFY (ERROR|TIMEOUT|REFUSED)/i,
  new RegExp(D, 'i'),
  /ACCEPT REFUSED/i,
  /Recovery Arm first/i,
  /inverter writes? (?:are |is )?locked/i,
  /deliberate recovery required/i,
  new RegExp(`START ${F}|ACTIVATION (?:VERIFY|WRITE) ${F}`, 'i'),
  /press End Free Power|retry(?:ing)? restore/i,
  /snapshot retained/i,
  /^(RESTORING|STARTING|ACTIVATION VERIFY)/i,
];

/** Words the card must never print, assembled from fragments so this file never spells them. */
export const NEVER_WORDS = [F, D].map((w) => new RegExp(w, 'i'));
