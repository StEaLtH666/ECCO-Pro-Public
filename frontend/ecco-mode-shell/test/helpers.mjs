// Shared helpers for the node tests (not a test file itself: the test glob is test/*.test.mjs).
// The card under test is ../ecco-mode-shell.js, or the file named by ECCO_MODE_SHELL_PATH (the mutation runner points it at
// a mutated scratch copy). Fixtures are synthetic and live in ./fixtures.
import { readFileSync } from 'node:fs';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';

export const here = path.dirname(fileURLToPath(import.meta.url));
export const cardDir = path.resolve(here, '..');
export const CARD_PATH = process.env.ECCO_MODE_SHELL_PATH ? path.resolve(process.env.ECCO_MODE_SHELL_PATH) : path.join(cardDir, 'ecco-mode-shell.js');
export const cardUrl = pathToFileURL(CARD_PATH).href;
export const loadCard = (tag = 'x') => import(`${cardUrl}?${tag}`);

const fx = (n) => JSON.parse(readFileSync(path.join(here, 'fixtures', n), 'utf8'));
export const miniCatalogue = () => fx('mini.catalogue.json');
export const miniStatesRaw = () => fx('mini.states.json');
export const hostileStatesRaw = () => fx('hostile.states.json');

/** The tests' clock. */
export const NOW = Date.parse('2026-11-14T12:00:00Z');
const iso = (ms) => new Date(ms).toISOString();

/** A Home Assistant state object. ageS is how long ago it was last updated. */
export function mkState(id, state, attributes = {}, { ageS = 30, changedAgeS = null } = {}) {
  return {
    entity_id: id, state, attributes,
    last_changed: iso(NOW - (changedAgeS === null ? ageS : changedAgeS) * 1000),
    last_updated: iso(NOW - ageS * 1000),
  };
}

/** hass.states from a fixture object {entity_id: {state, attributes, age_s}} (keys starting with _ are notes). */
export function statesFrom(raw, now = NOW) {
  const out = {};
  for (const [id, e] of Object.entries(raw)) {
    if (id.startsWith('_')) continue;
    out[id] = {
      entity_id: id, state: e.state, attributes: structuredClone(e.attributes || {}),
      last_changed: iso(now - (e.age_s || 0) * 1000), last_updated: iso(now - (e.age_s || 0) * 1000),
    };
  }
  return out;
}

export const miniStates = (mutate = null) => {
  const s = statesFrom(miniStatesRaw());
  if (mutate) mutate(s);
  return s;
};

/** A hass stand-in with only the three things the card may read. */
export const makeHass = (states, extra = {}) => ({ states, locale: { language: 'en' }, themes: { darkMode: false }, ...extra });

/** A hass whose every function throws and whose every property read other than states / locale / themes throws. */
export function trapHass(states) {
  const reads = [];
  const calls = [];
  const boom = (name) => (...a) => {
    calls.push([name, a]);
    throw new Error(`hass.${name} must never be called`);
  };
  const target = {
    states, locale: { language: 'en' }, themes: { darkMode: false },
    callService: boom('callService'), callWS: boom('callWS'), callApi: boom('callApi'), sendWS: boom('sendWS'),
    fetchWithAuth: boom('fetchWithAuth'), connection: new Proxy({}, { get: (_t, p) => boom(`connection.${String(p)}`) }),
    auth: new Proxy({}, { get: (_t, p) => boom(`auth.${String(p)}`) }), user: { id: 'u', name: 'n', is_admin: true },
  };
  const allowed = new Set(['states', 'locale', 'themes']);
  const hass = new Proxy(target, {
    get(t, p) {
      reads.push(String(p));
      if (!allowed.has(p) && typeof p === 'string') {
        // reading any other property is itself a failure
        calls.push([`read:${p}`, []]);
      }
      return t[p];
    },
  });
  return { hass, reads, calls };
}

/**
 * Trap every API the shell must never touch (storage, network, history, window.open, cookies). Returns the hit list and a
 * restore function. Install it BEFORE the interaction under test.
 */
export function installTraps() {
  const hits = [];
  const saved = [];
  const defineTrap = (obj, name, label) => {
    const desc = Object.getOwnPropertyDescriptor(obj, name);
    saved.push([obj, name, desc]);
    Object.defineProperty(obj, name, {
      configurable: true,
      get() {
        hits.push(label);
        throw new Error(`${label} must never be touched`);
      },
      set() {
        hits.push(label);
        throw new Error(`${label} must never be touched`);
      },
    });
  };
  for (const n of ['localStorage', 'sessionStorage', 'indexedDB', 'fetch', 'XMLHttpRequest', 'WebSocket', 'EventSource', 'BroadcastChannel']) {
    defineTrap(globalThis, n, n);
  }
  const w = globalThis.window;
  for (const n of ['open', 'fetch', 'localStorage', 'sessionStorage']) defineTrap(w, n, `window.${n}`);
  w.history = new Proxy({}, { get: (_t, p) => { hits.push(`history.${String(p)}`); throw new Error('history must never be touched'); } });
  return {
    hits,
    restore() {
      for (const [obj, name, desc] of saved.reverse()) {
        if (desc) Object.defineProperty(obj, name, desc);
        else delete obj[name];
      }
      delete w.history;
    },
  };
}

/** Wait for the microtask queue (async child-card creation, clipboard promises). */
export const tick = () => new Promise((r) => setImmediate(r));

/** All text of a node tree. */
export const textOf = (n) => n.textContent.replace(/\s+/g, ' ').trim();
