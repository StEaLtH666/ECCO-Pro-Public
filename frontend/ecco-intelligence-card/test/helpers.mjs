// Shared helpers for the node tests (not a test file itself: the test glob is test/*.test.mjs).
// The golden contract fixtures are READ IN PLACE from intelligence/tests/fixtures/advisory_contract (never copied).
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

export const here = path.dirname(fileURLToPath(import.meta.url));
export const cardDir = path.resolve(here, '..');
export const repoRoot = path.resolve(cardDir, '..', '..');
export const fixtureDir = path.join(repoRoot, 'intelligence', 'tests', 'fixtures', 'advisory_contract');
export const FIXTURES = Object.freeze(['all_open_blocked', 'synthetic_ok', 'stale', 'paused', 'self_test_failed', 'starting']);
export const NULL_FIXTURES = Object.freeze(['stale', 'paused', 'self_test_failed', 'starting']);

export const card = await import('../ecco-intelligence-card.js');
export const ids = card.DEFAULT_ENTITIES;
export const env = card.makeFormatters({ locale: 'en-GB', timeZone: 'Europe/London' });
export const cfg = card.validateConfig({});

export function loadFixture(name) {
  return JSON.parse(readFileSync(path.join(fixtureDir, `${name}.json`), 'utf8'));
}

/** A Home Assistant state string for a published value: None -> unknown, a bool -> on / off, a float as Python prints it. */
export function haState(v) {
  if (v === null || v === undefined) return 'unknown';
  if (v === true) return 'on';
  if (v === false) return 'off';
  if (typeof v === 'number') return Number.isInteger(v) ? v.toFixed(1) : String(v);
  return String(v);
}

/** hass.states for a fixture: its eleven integration entities plus the package's two (pause off, watchdog on by default). */
export function statesFor(name, { paused = 'off', watchdog = 'on', fx = null } = {}) {
  const f = fx || loadFixture(name);
  const out = {};
  for (const [eid, e] of Object.entries(f.entities)) {
    out[eid] = {
      entity_id: eid, state: haState(e.state), attributes: structuredClone({ ...e.recorded, ...e.unrecorded }),
      last_updated: e.recorded.generated_at, last_changed: e.recorded.generated_at,
    };
  }
  if (paused !== null) out[ids.paused] = { entity_id: ids.paused, state: paused, attributes: {} };
  if (watchdog !== null) out[ids.watchdog_fresh] = { entity_id: ids.watchdog_fresh, state: watchdog, attributes: {} };
  return out;
}

/** The fixture's generated_at plus `afterS` seconds, as epoch ms (the card's clock in the tests). */
export function nowFor(name, afterS = 120) {
  const f = loadFixture(name);
  return Date.parse(f.entities[ids.status].recorded.generated_at) + afterS * 1000;
}

export function render(states, nowMs, { open = new Set(), config = cfg } = {}) {
  const vm = card.deriveModel(states, config.entities, nowMs);
  return { vm, html: card.renderCard(vm, config, env, open) };
}

export function renderFixture(name, { afterS = 120, mutate = null, ...opts } = {}) {
  const states = statesFor(name, opts);
  if (mutate) mutate(states);
  return render(states, nowFor(name, afterS));
}

const ENT = { '&amp;': '&', '&lt;': '<', '&gt;': '>', '&quot;': '"', '&#39;': "'" };
/** The visible text of an HTML string (tags removed, style blocks dropped, entities decoded). */
export function textOf(html) {
  return html.replace(/<style>[\s\S]*?<\/style>/g, '').replace(/<[^>]+>/g, ' ').replace(/&(amp|lt|gt|quot|#39);/g, (e) => ENT[e])
    .replace(/\s+/g, ' ').trim();
}

/** The markup without the labelled history block (the only place last_good figures may appear). */
export function withoutHistory(html) {
  return html.replace(/<details class="history"[\s\S]*?<\/details>/g, '');
}

/** A number followed by a unit the card uses for figures (%, kWh, p/kWh) or preceded by a pound sign. */
export const FIGURE_RE = /\d(?:[.,]\d+)?\s*(?:%|kWh|p\/kWh)|£\s*\d/;

/** Every numeric value a fixture publishes anywhere in its item and forecast entities and in last_good. */
export function fixtureNumbers(name) {
  const f = loadFixture(name);
  const nums = new Set();
  const walk = (v) => {
    if (typeof v === 'number' && Number.isFinite(v)) nums.add(v);
    else if (Array.isArray(v)) v.forEach(walk);
    else if (v && typeof v === 'object') Object.values(v).forEach(walk);
  };
  for (const [eid, e] of Object.entries(f.entities)) {
    if (eid === ids.status) walk(e.unrecorded.last_good);
    else if (eid !== ids.accuracy && eid !== ids.data_quality && eid !== ids.fresh) walk([e.state, e.recorded, e.unrecorded]);
  }
  return [...nums];
}
