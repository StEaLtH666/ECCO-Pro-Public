/*
 * ECCO Intelligence card: the read-only presentation of ECCO Intelligence SHADOW advice (contract ecco-intel-entities/1).
 *
 * One dependency-free ES module: no build step, no npm packages, no network, no CDN, no web fonts, no images. Home Assistant
 * loads it as a JavaScript module resource; the node tests in ./test import the same file, so the pure core below is
 * EXPORTED. Its one import-time side effect registers the custom element (guarded: only when customElements exists and the
 * tag is free) and the card-picker entry.
 *
 * What this card does, and nothing else: it READS the ecco-intel-entities/1 entities from hass.states and renders them.
 *   - It has NO write path: no service call, no websocket message, no button press, no fetch, XMLHttpRequest or WebSocket,
 *     no eval, no storage. It does not read anything from hass except hass.states.
 *   - The pause control is NOT here. The dashboard offers it as a core tile card on input_boolean.ecco_intel_paused; this
 *     card only shows the helper's state.
 *
 * Guards (fail closed):
 *   - Advice renders only when the status entity carries contract_version 'ecco-intel-entities/1', a non-blank
 *     integration_version (spaces only is blank), mode 'SHADOW' and applies_nothing === true, kind 'status', and its state
 *     is a known status. Otherwise the card shows one fixed notice, 'Intelligence output not recognised', and nothing from
 *     the output.
 *   - The null rule: no figure for a BLOCKED, INSUFFICIENT_DATA, NO_ADVICE or WITHHELD item, and none at all under STALE,
 *     PAUSED, SELF_TEST_FAILED or STARTING. last_good appears only as clearly labelled history with its time.
 *   - No figure at all, with a notice saying why, while the result is not current: the card's clock is past the status's
 *     valid_until ('expired'), the status's generated_at is more than CLOCK_AHEAD_MS ahead of the card's clock
 *     ('clock_ahead': this device's clock lags, so its validity cannot be checked here), or the package's watchdog, which
 *     judges freshness on Home Assistant's clock, reads 'off' ('watchdog_off'). A missing or unknown watchdog leaves the
 *     card's own clock checks.
 *   - A figure also needs the item entity's own contract fields, its kind, its status OK, a finite state, the status's
 *     generated_at and the card's clock at or before both its own and the status's valid_until. The accuracy and data
 *     quality entities are used only when their generated_at is the status's (the same publish).
 *   - Every string that comes from the entities is escaped (esc) before it reaches the markup.
 *
 * Every entity id comes from the card configuration; the defaults are the contract's ENTITY_IDS. The frozen V1 prototype's
 * sensor.ecco_intelligence_* ids are refused: they are not this contract.
 *
 * Layout of this file:
 *   1. constants and configuration validation
 *   2. parsing and the guards
 *   3. text tables (every user-visible string lives here)
 *   4. state derivation (deriveModel)
 *   5. HTML renderers (pure: they return strings)
 *   6. the custom element
 */

// ===========================================================================
// 1. constants and configuration validation
// ===========================================================================
export const TAG = 'ecco-intelligence-card';
export const VERSION = '0.1.0';
export const CONTRACT_VERSION = 'ecco-intel-entities/1';
export const MODE = 'SHADOW';
export const DEFAULT_TITLE = 'ECCO Intelligence';
export const TICK_MS = 30000; // re-render for the report age and the validity check
// PROPOSED (mirrors the package watchdog's PROPOSED CLOCK_AHEAD_S = 120): a result timed further ahead of this device's
// clock than this is not shown as current
export const CLOCK_AHEAD_MS = 120000;
export const BANNER_TEXT = 'SHADOW MODE - advice only, nothing is applied';

// The contract's ENTITY_IDS (intelligence/advisory_contract.py); tools/tests/test_intelligence_card.py pins them equal.
export const DEFAULT_ENTITIES = Object.freeze({
  status: 'sensor.ecco_intel_status',
  charge_target: 'sensor.ecco_intel_charge_target',
  overnight_demand: 'sensor.ecco_intel_overnight_demand',
  export_event: 'sensor.ecco_intel_export_event',
  dump_to_grid: 'sensor.ecco_intel_dump_to_grid',
  predicted_day_load: 'sensor.ecco_intel_predicted_day_load',
  pv_tomorrow: 'sensor.ecco_intel_pv_tomorrow',
  predicted_morning_soc: 'sensor.ecco_intel_predicted_morning_soc',
  accuracy: 'sensor.ecco_intel_accuracy',
  data_quality: 'sensor.ecco_intel_data_quality',
  fresh: 'binary_sensor.ecco_intel_fresh',
  paused: 'input_boolean.ecco_intel_paused',
  watchdog_fresh: 'binary_sensor.ecco_intel_watchdog_fresh',
});
export const ENTITY_KEYS = Object.freeze(Object.keys(DEFAULT_ENTITIES));
const ENTITY_DOMAIN = Object.freeze(Object.fromEntries(ENTITY_KEYS.map((k) => [k, DEFAULT_ENTITIES[k].split('.')[0]])));

export const SYSTEM_STATUSES = Object.freeze(['PAUSED', 'SELF_TEST_FAILED', 'STALE', 'STARTING', 'BLOCKED', 'INSUFFICIENT_DATA', 'NO_ADVICE', 'OK']);
export const NULL_STATUSES = Object.freeze(['STARTING', 'PAUSED', 'STALE', 'SELF_TEST_FAILED']);
export const ITEM_STATUSES = Object.freeze(['OK', 'BLOCKED', 'INSUFFICIENT_DATA', 'NO_ADVICE', 'WITHHELD']);
export const ADVICE_ITEMS = Object.freeze(['charge_target', 'overnight_demand', 'export_event', 'dump_to_grid']);
export const FORECAST_ITEMS = Object.freeze(['predicted_day_load', 'pv_tomorrow', 'predicted_morning_soc']);
export const ITEM_UNITS = Object.freeze({
  charge_target: '%', overnight_demand: 'kWh', export_event: 'kWh', dump_to_grid: 'kWh',
  predicted_day_load: 'kWh', pv_tomorrow: 'kWh', predicted_morning_soc: '%',
});
export const VERIFIED_TARIFF_PROVENANCES = Object.freeze(['VERIFIED', 'VERIFIED_FROM_INTEGRATION']);
export const DATA_QUALITY_STATES = Object.freeze(['OK', 'DEGRADED', 'BLOCKED', 'UNKNOWN']);
export const DECISION_STATUSES = Object.freeze(['OPEN', 'RECORDED', 'INVALID']);
// intelligence/site_decisions.py DECISION_TITLES under their display labels (pinned equal by the Python suite)
export const DECISION_TITLES = Object.freeze({
  'I-D1': 'Canonical soft planning floor',
  'I-D2': 'Inverter physical protection level',
  'I-D3': 'Battery capacity authority',
  'I-D4': 'Capacity mismatch band',
  'I-D5': 'Efficiency basis',
  'I-D6': 'Advisory freshness limits',
  'I-D7': 'Required signals per advisor (retired)',
  'I-D8': 'Derived house-load cut-over and pre-fix history',
  'I-D9': 'Clock-change night policy',
});
// The entity attributes this card reads: a subset of the contract's RECORDED_ATTRIBUTES and UNRECORDED_ATTRIBUTES (pinned by
// the Python suite). Every attribute is read through att(), with a literal name from this list.
export const ATTRIBUTES_READ = Object.freeze([
  'mode', 'applies_nothing', 'contract_version', 'integration_version', 'engine_version', 'kind', 'status', 'generated_at',
  'valid_until', 'next_run_at', 'blockers', 'reason_codes', 'decisions', 'pause_control', 'data_quality', 'tariff', 'value',
  'plan', 'self_test', 'input_ages', 'last_good', 'confidence', 'advice', 'p10', 'p90', 'coverage_7d', 'n',
]);
// keys read inside the pre-declared blocks and rows (the contract's BLOCK_KEYS / INPUT_AGE_KEYS / last_good / blockers)
export const BLOCK_KEYS_READ = Object.freeze({
  tariff: Object.freeze(['provenance', 'window', 'price_range']),
  value: Object.freeze(['range_gbp', 'assumptions']),
  plan: Object.freeze(['precharge_by', 'headroom_ceiling_pct', 'reserve_runout_at']),
  input_ages: Object.freeze(['name', 'age_s', 'limit_s', 'status']),
  last_good: Object.freeze(['generated_at', 'values']),
  blockers: Object.freeze(['code', 'text']),
});

const ENTITY_ID_RE = /^[a-z0-9_]+\.[a-z0-9_]+$/;
const PROTOTYPE_ID_RE = /\.ecco_intelligence_/; // the frozen V1 prototype's ids: never read

/**
 * Validate and normalise the card configuration. Throws an Error naming the offending key (Home Assistant shows it in the
 * card editor / error card). Every entity is optional in the configuration: a missing one takes the contract default.
 */
export function validateConfig(config) {
  if (!config || typeof config !== 'object' || Array.isArray(config)) {
    throw new Error(`${TAG}: invalid configuration`);
  }
  const known = new Set(['type', 'title', 'entities']);
  for (const k of Object.keys(config)) {
    if (!known.has(k)) throw new Error(`${TAG}: ${k} is not a known option`);
  }
  if (config.title !== undefined && (typeof config.title !== 'string' || config.title.length > 80)) {
    throw new Error(`${TAG}: title must be a short text`);
  }
  const ent = config.entities === undefined || config.entities === null ? {} : config.entities;
  if (typeof ent !== 'object' || Array.isArray(ent)) throw new Error(`${TAG}: entities must be a mapping`);
  for (const k of Object.keys(ent)) {
    if (!ENTITY_KEYS.includes(k)) throw new Error(`${TAG}: entities.${k} is not a known entity key`);
  }
  const out = {};
  const seen = new Map();
  for (const k of ENTITY_KEYS) {
    const v = ent[k] === undefined || ent[k] === null || ent[k] === '' ? DEFAULT_ENTITIES[k] : ent[k];
    if (typeof v !== 'string' || !ENTITY_ID_RE.test(v)) {
      throw new Error(`${TAG}: entities.${k} must be an entity id such as ${DEFAULT_ENTITIES[k]}`);
    }
    if (v.split('.')[0] !== ENTITY_DOMAIN[k]) throw new Error(`${TAG}: entities.${k} must be a ${ENTITY_DOMAIN[k]}.* entity`);
    if (PROTOTYPE_ID_RE.test(v)) {
      throw new Error(`${TAG}: entities.${k}: the ecco_intelligence_* ids belong to the frozen V1 prototype, not to ${CONTRACT_VERSION}`);
    }
    if (seen.has(v)) throw new Error(`${TAG}: entities.${k} repeats entities.${seen.get(v)}`);
    seen.set(v, k);
    out[k] = v;
  }
  return Object.freeze({ title: config.title === undefined ? DEFAULT_TITLE : config.title, entities: Object.freeze(out) });
}

// ===========================================================================
// 2. parsing and the guards
// ===========================================================================
const own = (o, k) => o !== null && typeof o === 'object' && Object.prototype.hasOwnProperty.call(o, k);

/** One attribute of a Home Assistant state object, or undefined. The only place `attributes` is read. */
export function att(st, name) {
  return st && own(st.attributes, name) ? st.attributes[name] : undefined;
}

/** A finite number from a number or a numeric text (Home Assistant states are text); anything else is null. */
export function finite(v) {
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  if (typeof v === 'string' && /^\s*-?\d+(?:\.\d+)?(?:e[-+]?\d+)?\s*$/i.test(v)) {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

/** Epoch ms from an ISO-8601 text with a date and an offset (the contract's timestamps), else null. */
export function parseTime(v) {
  if (typeof v !== 'string' || !/^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}/.test(v) || !/(?:Z|[+-]\d{2}:?\d{2})$/.test(v)) return null;
  const ms = Date.parse(v);
  return Number.isFinite(ms) ? ms : null;
}

const isText = (v) => typeof v === 'string' && v.length > 0;
const isNonBlank = (v) => typeof v === 'string' && v.trim().length > 0;
const textList = (v) => (Array.isArray(v) ? v.filter(isText) : []);
const live = (st) => !!st && typeof st.state === 'string' && st.state !== 'unavailable' && st.state !== 'unknown';

/** The contract fields every published entity carries. */
export function contractFields(st) {
  return att(st, 'contract_version') === CONTRACT_VERSION && att(st, 'mode') === MODE && att(st, 'applies_nothing') === true;
}

/**
 * Is this the status entity of ecco-intel-entities/1 in SHADOW mode? Returns the reason it is not (or '' when it is).
 * The card renders advice only for '' (see the module header).
 */
export function statusGuard(st) {
  if (!live(st)) return 'not_publishing';
  if (!contractFields(st)) return 'not_recognised';
  if (!isNonBlank(att(st, 'integration_version'))) return 'not_recognised';
  if (att(st, 'kind') !== 'status' || att(st, 'status') !== st.state) return 'not_recognised';
  if (!SYSTEM_STATUSES.includes(st.state)) return 'not_recognised';
  return '';
}

function blockerRows(v) {
  if (!Array.isArray(v)) return [];
  return v.filter((b) => own(b, 'code') && isText(b.code)).map((b) => ({ code: b.code, text: isText(b.text) ? b.text : '' }));
}

/** A two-number range from [a, b], {min, max} or {low, high}; else null. */
export function range2(v) {
  let a = null;
  let b = null;
  if (Array.isArray(v) && v.length === 2) [a, b] = v;
  else if (own(v, 'min') && own(v, 'max')) [a, b] = [v.min, v.max];
  else if (own(v, 'low') && own(v, 'high')) [a, b] = [v.low, v.high];
  a = typeof a === 'number' ? finite(a) : null;
  b = typeof b === 'number' ? finite(b) : null;
  return a !== null && b !== null && a <= b ? [a, b] : null;
}

// ===========================================================================
// 3. text tables (every user-visible string lives here)
// ===========================================================================
// pill: always in the header; title / body: the callout (none for OK)
export const STATUS_COPY = Object.freeze({
  OK: Object.freeze({ pill: 'Advice ready', tone: 'ok', title: null, body: null }),
  NO_ADVICE: Object.freeze({
    pill: 'No advice needed', tone: 'ok', title: 'No advice this time',
    body: 'ECCO Intelligence ran and has nothing to advise for this period.',
  }),
  BLOCKED: Object.freeze({
    pill: 'Blocked', tone: 'warn', title: 'Advice blocked',
    body: 'Battery advice is withheld until the conditions below are met. Nothing is applied either way.',
  }),
  INSUFFICIENT_DATA: Object.freeze({
    pill: 'Not enough data', tone: 'warn', title: 'Not enough data yet',
    body: 'ECCO Intelligence does not have enough recent data to advise. Figures appear once it has.',
  }),
  STALE: Object.freeze({
    pill: 'Stale', tone: 'bad', title: 'Result is stale',
    body: 'The last result is older than its validity. No figures are shown until a fresh result arrives.',
  }),
  PAUSED: Object.freeze({
    pill: 'Paused', tone: 'idle', title: 'Paused',
    body: 'ECCO Intelligence is paused with the ECCO Intel Paused switch. It produces no advice until the switch is off.',
  }),
  SELF_TEST_FAILED: Object.freeze({
    pill: 'Self-test failed', tone: 'bad', title: 'Self-test failed',
    body: 'ECCO Intelligence failed its start-up self-test and publishes no advice. The failed checks are listed below.',
  }),
  STARTING: Object.freeze({
    pill: 'Starting', tone: 'idle', title: 'Starting',
    body: 'ECCO Intelligence is starting. The first result normally follows within a few minutes.',
  }),
});
// card-side states, independent of the engine status
export const NOTICE_COPY = Object.freeze({
  not_publishing: Object.freeze({ title: 'ECCO Intelligence is not publishing.', body: 'The status entity is missing, unknown or unavailable.' }),
  not_recognised: Object.freeze({
    title: 'Intelligence output not recognised',
    body: `This card shows only output of contract ${CONTRACT_VERSION} that is marked SHADOW and applies nothing. Nothing from this output is shown.`,
  }),
  // a live result whose figures are withheld (vm.withheld): the header pill and one callout
  expired: Object.freeze({
    pill: 'Expired', title: 'Result expired', body: 'This result is past its validity. No figures are shown until a fresh result arrives.',
  }),
  clock_ahead: Object.freeze({
    pill: 'Not current', title: 'Result time is ahead of this device',
    body: 'This result is timed more than 2 minutes after this device\'s clock, so its validity cannot be checked here. No figures are shown. Check the clock of this device and of Home Assistant.',
  }),
  watchdog_off: Object.freeze({
    pill: 'Not current', title: 'Result not confirmed fresh',
    body: 'The ECCO Intel watchdog in Home Assistant does not see this result as fresh. No figures are shown until it does.',
  }),
});
export const WITHHELD_REASONS = Object.freeze(['expired', 'clock_ahead', 'watchdog_off']);
export const ITEM_LABEL = Object.freeze({
  charge_target: 'Next charge target',
  overnight_demand: 'Overnight demand',
  export_event: 'Export event',
  dump_to_grid: 'Dump to Grid',
  predicted_day_load: 'Demand forecast (day)',
  pv_tomorrow: 'Solar tomorrow',
  predicted_morning_soc: 'Predicted morning battery',
});
export const ITEM_STATUS_TEXT = Object.freeze({
  OK: '',
  BLOCKED: 'Blocked',
  INSUFFICIENT_DATA: 'Not enough data',
  NO_ADVICE: 'No advice',
  WITHHELD: 'Withheld',
});
export const TEXT = Object.freeze({
  noAdvice: 'No advice',
  notAvailable: 'Not available',
  updating: 'Updating',
  shadowAdvice: 'shadow advice, not applied',
  predicted: 'predicted',
  tariffNotVerified: 'Tariff not verified',
  tariffFormat: 'given, in a format this card does not read',
  history: 'History: last good result',
  historyNote: 'Not current advice. Shown for reference only; nothing here is applied.',
  drill: 'Details',
  reasons: 'Reasons',
  confidence: 'Confidence',
  blocked: 'Blocked conditions',
  decisions: 'Open decisions',
  accuracy: 'Recent accuracy',
  inputs: 'Input ages',
  dataQuality: 'Data quality',
  selfTest: 'Self-test checks',
  watchdog: 'Watchdog',
  pause: 'Pause',
  pauseHint: 'change it with the Pause tile',
  pauseOnNotYet: 'The pause is on; the next result will be PAUSED.',
  pauseMissing: 'The integration cannot see the pause helper (PAUSE_CONTROL_MISSING): install the ECCO Intelligence package.',
  none: 'none',
  integration: 'Integration',
  notCurrent: 'not current: shown only with a result inside its validity',
  seeDetails: '(see Details for the conditions)',
});

// ===========================================================================
// 4. state derivation
// ===========================================================================
function itemView(key, st, status, numbers, nowMs) {
  const v = {
    key, label: ITEM_LABEL[key], unit: ITEM_UNITS[key], recognised: false, status: null, value: null, band: null,
    confidence: null, blockers: [], reasons: [], advice: null, validMs: null, note: '',
  };
  if (!st) {
    v.note = TEXT.notAvailable;
    return v;
  }
  if (!contractFields(st) || att(st, 'kind') !== key || !ITEM_STATUSES.includes(att(st, 'status'))) {
    v.note = TEXT.notAvailable;
    return v;
  }
  v.recognised = true;
  v.status = att(st, 'status');
  v.confidence = isText(att(st, 'confidence')) ? att(st, 'confidence') : null;
  v.blockers = blockerRows(att(st, 'blockers'));
  v.reasons = textList(att(st, 'reason_codes'));
  if (v.status !== 'OK') {
    v.note = ITEM_STATUS_TEXT[v.status];
    return v;
  }
  // the null rule, re-checked with the card's clock: a figure only for an OK item of a live, valid result of the same cycle
  const valid = parseTime(att(st, 'valid_until'));
  const value = finite(st.state);
  if (!numbers.allowed || att(st, 'generated_at') !== numbers.generatedAt) {
    v.note = numbers.allowed ? TEXT.updating : TEXT.noAdvice;
    return v;
  }
  if (value === null || valid === null || nowMs > valid) {
    v.note = TEXT.notAvailable;
    return v;
  }
  v.value = value;
  v.validMs = valid;
  const lo = finite(att(st, 'p10'));
  const hi = finite(att(st, 'p90'));
  if (typeof att(st, 'p10') === 'number' && typeof att(st, 'p90') === 'number' && lo !== null && hi !== null && lo <= hi) v.band = [lo, hi];
  const adv = att(st, 'advice');
  v.advice = adv !== null && typeof adv === 'object' && !Array.isArray(adv) ? adv : null;
  return v;
}

/**
 * The whole view model from hass.states (`states`), the configured ids and the card's clock. Pure.
 * kind: 'not_publishing' | 'not_recognised' | 'null' (STARTING / PAUSED / STALE / SELF_TEST_FAILED) | 'live'.
 */
export function deriveModel(states, ids = DEFAULT_ENTITIES, nowMs = Date.now()) {
  const S = states || {};
  const st = S[ids.status];
  const vm = { kind: '', status: null, nowMs, watchdog: 'missing', paused: 'missing' };
  const wd = S[ids.watchdog_fresh];
  vm.watchdog = wd ? (wd.state === 'on' ? 'on' : wd.state === 'off' ? 'off' : 'unknown') : 'missing';
  const pz = S[ids.paused];
  vm.paused = pz ? (pz.state === 'on' ? 'on' : pz.state === 'off' ? 'off' : 'unknown') : 'missing';
  const why = statusGuard(st);
  if (why) {
    vm.kind = why;
    return vm;
  }
  vm.status = st.state;
  vm.kind = NULL_STATUSES.includes(st.state) ? 'null' : 'live';
  vm.generatedAt = att(st, 'generated_at');
  vm.genMs = parseTime(vm.generatedAt);
  vm.validMs = parseTime(att(st, 'valid_until'));
  vm.nextMs = parseTime(att(st, 'next_run_at'));
  vm.integrationVersion = att(st, 'integration_version');
  vm.engineVersion = isText(att(st, 'engine_version')) ? att(st, 'engine_version') : '';
  vm.blockers = blockerRows(att(st, 'blockers'));
  vm.reasons = textList(att(st, 'reason_codes'));
  vm.pauseControl = isText(att(st, 'pause_control')) ? att(st, 'pause_control') : null;
  const dec = att(st, 'decisions');
  vm.decisions = Object.keys(DECISION_TITLES).map((label) => ({
    label, title: DECISION_TITLES[label], status: own(dec, label) && DECISION_STATUSES.includes(dec[label]) ? dec[label] : 'UNKNOWN',
  }));
  vm.expired = vm.kind === 'live' && vm.validMs !== null && nowMs > vm.validMs;
  vm.clockAhead = vm.kind === 'live' && vm.genMs !== null && vm.genMs > nowMs + CLOCK_AHEAD_MS;
  // why a live result's figures are withheld ('' = they are not): the card's clock, then Home Assistant's watchdog
  vm.withheld = vm.kind !== 'live' ? '' : vm.expired ? 'expired' : vm.clockAhead ? 'clock_ahead' : vm.watchdog === 'off' ? 'watchdog_off' : '';
  const numbers = { allowed: vm.kind === 'live' && vm.withheld === '' && vm.validMs !== null && vm.genMs !== null, generatedAt: vm.generatedAt };
  vm.numbersAllowed = numbers.allowed;
  vm.items = [...ADVICE_ITEMS, ...FORECAST_ITEMS].map((k) => itemView(k, S[ids[k]], vm.status, numbers, nowMs));
  const item = (k) => vm.items.find((i) => i.key === k);
  const ctFigure = item('charge_target').value !== null;

  // the null rule: under a null-rule status nothing but history (last_good) and the self-test checks
  if (vm.kind === 'null') {
    const lg = att(st, 'last_good');
    const lgValues = own(lg, 'values') && lg.values && typeof lg.values === 'object' ? lg.values : {};
    const rows = [...ADVICE_ITEMS, ...FORECAST_ITEMS].filter((k) => own(lgValues, k) && typeof lgValues[k] === 'number' && finite(lgValues[k]) !== null)
      .map((k) => ({ key: k, label: ITEM_LABEL[k], unit: ITEM_UNITS[k], value: lgValues[k] }));
    vm.lastGood = own(lg, 'generated_at') && parseTime(lg.generated_at) !== null && rows.length ? { genMs: parseTime(lg.generated_at), rows } : null;
    const stt = att(st, 'self_test');
    vm.selfTest = stt && typeof stt === 'object' && !Array.isArray(stt)
      ? Object.keys(stt).filter((k) => isText(stt[k])).map((k) => ({ code: k, result: stt[k] })) : [];
    return vm;
  }

  // live: the pre-declared blocks, each under its own condition
  const tariff = att(st, 'tariff');
  const prov = own(tariff, 'provenance') && isText(tariff.provenance) ? tariff.provenance : null;
  vm.tariff = { verified: VERIFIED_TARIFF_PROVENANCES.includes(prov), provenance: prov, window: null, windowRaw: false, price: null };
  if (vm.tariff.verified && numbers.allowed) {
    const w = own(tariff, 'window') ? tariff.window : null;
    const ends = Array.isArray(w) && w.length === 2 ? w : own(w, 'start') && own(w, 'end') ? [w.start, w.end] : null;
    const ms = ends ? ends.map(parseTime) : null;
    if (ms && ms[0] !== null && ms[1] !== null && ms[0] < ms[1]) vm.tariff.window = ms;
    else vm.tariff.windowRaw = w !== null && w !== undefined;
    vm.tariff.price = own(tariff, 'price_range') ? range2(tariff.price_range) : null;
  }
  const value = att(st, 'value');
  const gbp = own(value, 'range_gbp') ? range2(value.range_gbp) : null;
  const assumptions = own(value, 'assumptions') ? (isText(value.assumptions) ? [value.assumptions] : textList(value.assumptions)) : [];
  vm.value = vm.tariff.verified && numbers.allowed && ctFigure && gbp && assumptions.length ? { range: gbp, assumptions } : null;
  const plan = att(st, 'plan');
  vm.plan = null;
  if (numbers.allowed && ctFigure && plan && typeof plan === 'object') {
    const pre = own(plan, 'precharge_by') ? parseTime(plan.precharge_by) : null;
    const head = own(plan, 'headroom_ceiling_pct') && typeof plan.headroom_ceiling_pct === 'number' ? finite(plan.headroom_ceiling_pct) : null;
    const run = own(plan, 'reserve_runout_at') ? parseTime(plan.reserve_runout_at) : null;
    if (pre !== null || head !== null || run !== null) vm.plan = { precharge: pre, headroom: head, runout: run };
  }
  // the diagnostic entities only from the same publish as the status (generated_at equal); otherwise the status's own word
  const dq = S[ids.data_quality];
  const dqState = dq && contractFields(dq) && att(dq, 'generated_at') === vm.generatedAt && DATA_QUALITY_STATES.includes(dq.state)
    ? dq.state : att(st, 'data_quality');
  vm.dataQuality = DATA_QUALITY_STATES.includes(dqState) ? dqState : 'UNKNOWN';
  const ages = numbers.allowed ? att(st, 'input_ages') : null;      // diagnostics of a current result only
  vm.inputAges = Array.isArray(ages)
    ? ages.filter((a) => own(a, 'name') && isText(a.name)).map((a) => ({
      name: a.name,
      age: typeof a.age_s === 'number' ? finite(a.age_s) : null,
      limit: typeof a.limit_s === 'number' ? finite(a.limit_s) : null,
      status: isText(a.status) ? a.status : 'unknown',
    }))
    : [];
  const acc = S[ids.accuracy];
  vm.accuracy = null;
  if (numbers.allowed && acc && contractFields(acc) && att(acc, 'status') === vm.status && att(acc, 'generated_at') === vm.generatedAt) {
    const mae = finite(acc.state);
    const cov = typeof att(acc, 'coverage_7d') === 'number' ? finite(att(acc, 'coverage_7d')) : null;
    const n = Number.isInteger(att(acc, 'n')) ? att(acc, 'n') : null;
    if (mae !== null || cov !== null || n !== null) vm.accuracy = { mae, coverage: cov, n };
  }
  return vm;
}

// ===========================================================================
// 5. HTML renderers (pure functions returning strings)
// ===========================================================================
export const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

export function makeFormatters({ locale = 'en-GB', timeZone = 'Europe/London' } = {}) {
  const fmt = (ms, opts) => {
    try {
      return new Intl.DateTimeFormat(locale, { ...opts, timeZone }).format(new Date(ms));
    } catch (e) {
      return new Date(ms).toISOString().slice(0, 16).replace('T', ' ');
    }
  };
  const time = (ms) => fmt(ms, { hour: '2-digit', minute: '2-digit', hour12: false });
  const dateTime = (ms) => fmt(ms, { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hour12: false });
  const age = (ms) => {
    if (!Number.isFinite(ms)) return '';
    if (ms < -CLOCK_AHEAD_MS) return 'in the future';
    if (ms < 0) return 'just now'; // a small clock difference, inside the PROPOSED tolerance
    const m = Math.floor(ms / 60000);
    if (m < 1) return 'just now';
    if (m < 60) return `${m} min ago`;
    const h = Math.floor(m / 60);
    if (h < 48) return `${h} h ${m % 60} min ago`;
    return `${Math.floor(h / 24)} days ago`;
  };
  return { time, dateTime, age };
}

/** Rounding: SOC to a whole %, kWh to 0.1 (20 kWh and over to a whole kWh), money to the penny. */
export function figure(value, unit) {
  if (unit === '%') return `${Math.round(value)}%`;
  if (unit === 'kWh') return Math.abs(value) >= 20 ? `${Math.round(value)} kWh` : `${(Math.round(value * 10) / 10).toFixed(1)} kWh`;
  if (unit === 'GBP') return `£${value.toFixed(2)}`;
  if (unit === 'p/kWh') return `${value.toFixed(1)} p/kWh`;
  return String(value);
}

const fig = (key, text, cls = '') => `<span class="fig${cls ? ` ${cls}` : ''}" data-fig="${esc(key)}">${esc(text)}</span>`;
const list = (rows) => (rows.length ? `<ul>${rows.map((r) => `<li>${r}</li>`).join('')}</ul>` : `<p class="muted">${esc(TEXT.none)}</p>`);
const codeText = (b) => `<code>${esc(b.code)}</code>${b.text ? ` ${esc(b.text)}` : ''}`;

function renderHeader(vm, cfg, env) {
  const copy = vm.status ? STATUS_COPY[vm.status] : null;
  const held = vm.withheld ? NOTICE_COPY[vm.withheld] : null; // a withheld result never reads 'Advice ready'
  const pill = held ? `<span class="pill tone-bad" data-pill="${esc(vm.withheld)}">${esc(held.pill)}</span>`
    : copy ? `<span class="pill tone-${copy.tone}" data-pill="${esc(vm.status)}">${esc(copy.pill)}</span>` : '';
  const age = vm.genMs !== null && vm.genMs !== undefined
    ? `<span class="age" data-age>Report from ${esc(env.dateTime(vm.genMs))}, ${esc(env.age(vm.nowMs - vm.genMs))}`
      + `${vm.nextMs !== null && vm.nextMs > vm.nowMs ? ` · next refresh ${esc(env.time(vm.nextMs))}` : ''}</span>` : '';
  const badge = vm.kind === 'null' || vm.kind === 'live' ? `<span class="badge" data-badge="shadow">${esc(MODE)}</span>` : '';
  return `<header class="hdr"><h2 class="title">${esc(cfg.title)}</h2>${badge}${pill}${age}</header>`;
}

function callout(kind, title, body, tone) {
  if (!title) return '';
  return `<section class="callout tone-${tone}" data-callout="${esc(kind)}"><h3>${esc(title)}</h3>${body ? `<p>${esc(body)}</p>` : ''}</section>`;
}

function blockersOf(v) {
  return v.blockers.length ? `<ul class="blockers">${v.blockers.map((b) => `<li>${esc(b.text || b.code)}</li>`).join('')}</ul>` : '';
}

function renderChargeTarget(vm, env) {
  const v = vm.items.find((i) => i.key === 'charge_target');
  let body;
  if (v.value !== null) {
    const extra = [];
    if (v.advice && isText(v.advice.binding_constraint)) extra.push(`limited by ${esc(v.advice.binding_constraint)}`);
    if (v.confidence) extra.push(`confidence ${esc(v.confidence)}`);
    if (vm.plan && vm.plan.precharge !== null) extra.push(`charged by ${fig('plan_precharge', env.time(vm.plan.precharge))}`);
    if (vm.plan && vm.plan.headroom !== null) extra.push(`headroom ceiling ${fig('plan_headroom', figure(vm.plan.headroom, '%'))}`);
    if (vm.plan && vm.plan.runout !== null) extra.push(`reserve reached at ${fig('plan_runout', env.time(vm.plan.runout))}`);
    body = `<div class="hero-value">Charge to ${fig('charge_target', figure(v.value, '%'), 'rec')}</div>`
      + `<div class="sub">${esc(TEXT.shadowAdvice)}${extra.length ? ` · ${extra.join(' · ')}` : ''}</div>`;
  } else {
    body = `<div class="hero-value none" data-noadvice>${esc(TEXT.noAdvice)}</div>`
      + (v.note && v.note !== TEXT.noAdvice ? `<div class="sub">${esc(v.note)}</div>` : '') + blockersOf(v);
  }
  return `<section class="hero" data-item="charge_target"><h3>${esc(v.label)}</h3>${body}</section>`;
}

function itemRow(v) {
  let val;
  if (v.value !== null) {
    const isForecast = FORECAST_ITEMS.includes(v.key) || v.key === 'overnight_demand';
    const main = fig(v.key, `${isForecast ? '~' : ''}${figure(v.value, v.unit)}`, isForecast ? 'pred' : 'rec');
    const band = v.band ? ` <span class="band" data-band="${esc(v.key)}">(${esc(figure(v.band[0], v.unit))} to ${esc(figure(v.band[1], v.unit))})</span>` : '';
    const conf = v.confidence ? ` <span class="conf">${esc(v.confidence)}</span>` : '';
    val = `${main}${conf}${band}`;
  } else {
    // no count: a BLOCKED / INSUFFICIENT_DATA row shows no digit at all; the conditions are listed in Details
    const more = v.blockers.length ? ` <span class="muted" data-nblock>${esc(TEXT.seeDetails)}</span>` : '';
    val = `<span class="none">${esc(v.note || TEXT.noAdvice)}</span>${more}`;
  }
  return `<div class="row" data-item="${esc(v.key)}" data-status="${esc(v.status || 'NONE')}"><span class="lbl">${esc(v.label)}</span>`
    + `<span class="val">${val}</span></div>`;
}

function renderTariff(vm, env) {
  const t = vm.tariff;
  let body;
  if (!t.verified) body = `<span class="none" data-tariff="unverified">${esc(TEXT.tariffNotVerified)}</span>`;
  else {
    const parts = [`<span data-tariff="verified">${esc(t.provenance)}</span>`];
    if (t.window) parts.push(`cheap window ${fig('tariff_window', `${env.time(t.window[0])} to ${env.time(t.window[1])}`)}`);
    else if (t.windowRaw) parts.push(`window ${esc(TEXT.tariffFormat)}`);
    if (t.price) parts.push(`price ${fig('tariff_price', `${figure(t.price[0], 'p/kWh')} to ${figure(t.price[1], 'p/kWh')}`)}`);
    body = parts.join(' · ');
  }
  return `<div class="row" data-sec="tariff"><span class="lbl">Tariff</span><span class="val">${body}</span></div>`;
}

function renderValue(vm) {
  if (!vm.value) return '';
  const [lo, hi] = vm.value.range;
  return `<section class="block" data-sec="value"><h3>Estimated value</h3><p>${fig('value', `${figure(lo, 'GBP')} to ${figure(hi, 'GBP')}`, 'rec')}`
    + ` (${esc(TEXT.shadowAdvice)})</p><p class="muted">Assumptions:</p>${list(vm.value.assumptions.map(esc))}</section>`;
}

function renderQuality(vm) {
  const rows = vm.inputAges.map((a) => {
    const age = a.age === null ? 'age unknown' : `${Math.round(a.age)} s old`;
    const lim = a.limit === null ? 'no limit' : `limit ${Math.round(a.limit)} s`;
    return `<code>${esc(a.name)}</code> ${esc(age)} (${esc(lim)}), ${esc(a.status)}`;
  });
  return `<section class="block" data-sec="quality"><h3>${esc(TEXT.dataQuality)}: <span data-dq="${esc(vm.dataQuality)}">${esc(vm.dataQuality)}</span></h3>`
    + `<p class="muted">${esc(TEXT.inputs)}</p>${vm.numbersAllowed ? list(rows) : `<p class="muted">${esc(TEXT.notCurrent)}</p>`}</section>`;
}

function renderDrill(vm, open) {
  const reasons = [...vm.reasons.map((c) => `<code>${esc(c)}</code>`)];
  const conf = [];
  const blocked = vm.blockers.map(codeText);
  for (const v of vm.kind === 'live' ? vm.items : []) {
    if (v.reasons.length) reasons.push(`${esc(v.label)}: ${v.reasons.map((c) => `<code>${esc(c)}</code>`).join(', ')}`);
    if (v.confidence) conf.push(`${esc(v.label)}: ${esc(v.confidence)}`);
    for (const b of v.blockers) blocked.push(`${esc(v.label)}: ${codeText(b)}`);
  }
  const openDec = vm.decisions.filter((d) => d.status !== 'RECORDED').map((d) => `<strong>${esc(d.label)}</strong> ${esc(d.title)}: ${esc(d.status)}`);
  let acc = '';
  if (vm.kind === 'live') {
    const a = vm.accuracy;
    const parts = [];
    if (a && a.mae !== null) parts.push(`7-day mean error of the load forecasts ${fig('accuracy_mae', figure(a.mae, 'kWh'))}`);
    if (a && a.coverage !== null) parts.push(`inside its range ${fig('accuracy_coverage', `${Math.round(a.coverage * 100)}%`)} of the time`);
    if (a && a.n !== null) parts.push(`${fig('accuracy_n', String(a.n))} forecasts scored`);
    acc = `<h4>${esc(TEXT.accuracy)}</h4>${parts.length ? `<p>${parts.join(', ')}</p>` : `<p class="muted">${esc(TEXT.none)}</p>`}`;
  }
  const meta = `<p class="muted">${esc(TEXT.integration)} ${esc(vm.integrationVersion)}${vm.engineVersion ? ` · engine ${esc(vm.engineVersion)}` : ''}</p>`;
  return `<details class="drill" data-k="drill"${open.has('drill') ? ' open' : ''}><summary>${esc(TEXT.drill)}</summary>`
    + `<h4>${esc(TEXT.reasons)}</h4>${list(reasons)}<h4>${esc(TEXT.confidence)}</h4>${list(conf)}`
    + `<h4>${esc(TEXT.blocked)}</h4>${list(blocked)}<h4>${esc(TEXT.decisions)}</h4>${list(openDec)}${acc}${meta}</details>`;
}

function renderHistory(vm, env, open) {
  if (!vm.lastGood) return '';
  const rows = vm.lastGood.rows.map((r) => `${esc(r.label)}: ${esc(figure(r.value, r.unit))}`);
  return `<details class="history" data-k="history" data-history="1"${open.has('history') ? ' open' : ''}>`
    + `<summary>${esc(TEXT.history)} from ${esc(env.dateTime(vm.lastGood.genMs))}</summary>`
    + `<p class="muted">${esc(TEXT.historyNote)}</p>${list(rows)}</details>`;
}

function renderFooter(vm) {
  const wd = { on: 'fresh', off: 'not fresh', unknown: 'unknown', missing: 'not installed' }[vm.watchdog];
  const pz = { on: 'on', off: 'off', unknown: 'unknown', missing: 'not installed' }[vm.paused];
  let note = vm.paused === 'on' && vm.status && vm.status !== 'PAUSED' ? `<p class="muted" data-pausenote>${esc(TEXT.pauseOnNotYet)}</p>` : '';
  if (vm.pauseControl === 'MISSING') note += `<p class="muted" data-pausemissing>${esc(TEXT.pauseMissing)}</p>`;
  const hint = vm.paused === 'missing' ? '' : ` (${esc(TEXT.pauseHint)})`; // no tile to point at without the helper
  return `<footer class="ftr">${note}<span data-watchdog="${esc(vm.watchdog)}">${esc(TEXT.watchdog)}: ${esc(wd)}</span>`
    + `<span data-pause="${esc(vm.paused)}">${esc(TEXT.pause)}: ${esc(pz)}${hint}</span></footer>`;
}

/** The card's markup for a view model. `open` is the set of details keys to keep open. */
export function renderCard(vm, cfg = validateConfig({}), env = makeFormatters(), open = new Set()) {
  const banner = `<div class="banner" data-sec="banner">${esc(BANNER_TEXT)}</div>`;
  if (vm.kind === 'not_recognised') {
    const n = NOTICE_COPY.not_recognised;
    return `<ha-card class="eic" data-kind="not_recognised"><header class="hdr"><h2 class="title">${esc(cfg.title)}</h2></header>`
      + `${callout('not_recognised', n.title, n.body, 'bad')}</ha-card>`;
  }
  if (vm.kind === 'not_publishing') {
    const n = NOTICE_COPY.not_publishing;
    return `<ha-card class="eic" data-kind="not_publishing">${banner}${renderHeader(vm, cfg, env)}`
      + `${callout('not_publishing', n.title, n.body, 'idle')}${renderFooter(vm)}</ha-card>`;
  }
  const copy = STATUS_COPY[vm.status];
  const parts = [banner, renderHeader(vm, cfg, env), callout(vm.status, copy.title, copy.body, copy.tone)];
  if (vm.kind === 'null') {
    if (vm.status === 'SELF_TEST_FAILED') {
      parts.push(`<section class="block" data-sec="selftest"><h3>${esc(TEXT.selfTest)}</h3>${list(vm.selfTest.map((c) => `<code>${esc(c.code)}</code> ${esc(c.result)}`))}</section>`);
    }
    if (vm.blockers.length && vm.status !== 'SELF_TEST_FAILED') parts.push(`<section class="block" data-sec="blockers">${list(vm.blockers.map((b) => esc(b.text || b.code)))}</section>`);
    parts.push(renderHistory(vm, env, open), renderDrill(vm, open), renderFooter(vm));
    return `<ha-card class="eic" data-kind="null" data-status="${esc(vm.status)}">${parts.join('')}</ha-card>`;
  }
  if (vm.withheld) {
    const n = NOTICE_COPY[vm.withheld];
    parts.push(callout(vm.withheld, n.title, n.body, 'bad'));
  }
  if (vm.status !== 'OK' && vm.blockers.length) {
    parts.push(`<section class="block" data-sec="blockers">${list(vm.blockers.map((b) => esc(b.text || b.code)))}</section>`);
  }
  parts.push(renderChargeTarget(vm, env));
  const rows = vm.items.filter((v) => v.key !== 'charge_target');
  parts.push(`<section class="block grid" data-sec="items">${rows.filter((v) => ADVICE_ITEMS.includes(v.key)).map(itemRow).join('')}</section>`);
  parts.push(`<section class="block grid" data-sec="forecasts"><h3>Forecasts</h3>${rows.filter((v) => FORECAST_ITEMS.includes(v.key)).map(itemRow).join('')}`
    + `${renderTariff(vm, env)}</section>`);
  parts.push(renderValue(vm), renderQuality(vm), renderDrill(vm, open), renderFooter(vm));
  return `<ha-card class="eic" data-kind="live" data-status="${esc(vm.status)}">${parts.join('')}</ha-card>`;
}

export const STYLE = `
:host { display: block; }
.eic {
  --eic-fg: var(--primary-text-color, #1b2330);
  --eic-fg2: var(--secondary-text-color, #556070);
  --eic-bg: var(--ha-card-background, var(--card-background-color, #ffffff));
  --eic-line: var(--divider-color, rgba(0, 0, 0, 0.12));
  /* theme-adaptive accents: each hue mixed with the theme's own text colour keeps at least 5.5:1 contrast on light and dark
     Home Assistant themes without reading the theme from hass */
  --eic-rec: color-mix(in srgb, #7357ff 62%, var(--eic-fg));
  --eic-pred: color-mix(in srgb, #1f7ae0 62%, var(--eic-fg));
  --eic-ok: color-mix(in srgb, #1f9d55 60%, var(--eic-fg));
  --eic-warn: color-mix(in srgb, #d98200 62%, var(--eic-fg));
  --eic-bad: color-mix(in srgb, #e5372c 62%, var(--eic-fg));
  --eic-idle: var(--eic-fg2);
  container-type: inline-size;
  display: block; box-sizing: border-box; padding: 14px 16px 12px; color: var(--eic-fg); background: var(--eic-bg);
  border-radius: var(--ha-card-border-radius, 12px); border: 1px solid var(--eic-line); font-size: 14px; line-height: 1.45;
  overflow-wrap: anywhere;
}
.eic * { box-sizing: border-box; }
.banner { margin: -14px -16px 10px; padding: 6px 16px; font-size: 12px; font-weight: 700; letter-spacing: 0.4px;
  color: var(--eic-rec); border-bottom: 1px dashed var(--eic-rec); border-radius: 12px 12px 0 0; }
.hdr { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 10px; margin-bottom: 8px; }
.title { margin: 0; font-size: 18px; font-weight: 600; }
.badge { font-size: 11px; font-weight: 700; padding: 1px 7px; border-radius: 999px; border: 1px dashed var(--eic-rec); color: var(--eic-rec); }
.pill { font-size: 12px; font-weight: 700; padding: 2px 9px; border-radius: 999px; border: 1px solid currentColor; }
.tone-ok { color: var(--eic-ok); } .tone-warn { color: var(--eic-warn); } .tone-bad { color: var(--eic-bad); } .tone-idle { color: var(--eic-idle); }
.age { flex-basis: 100%; font-size: 12px; color: var(--eic-fg2); }
.callout { margin: 8px 0; padding: 8px 12px; border-left: 4px solid currentColor; border-radius: 6px; background: color-mix(in srgb, currentColor 8%, transparent); }
.callout h3 { margin: 0 0 2px; font-size: 14px; }
.callout p { margin: 0; color: var(--eic-fg); }
.hero { margin: 10px 0; padding: 10px 12px; border: 1px solid var(--eic-rec); border-radius: 10px; }
.hero h3, .block h3 { margin: 0 0 4px; font-size: 13px; font-weight: 600; color: var(--eic-fg2); text-transform: uppercase; letter-spacing: 0.3px; }
.hero-value { font-size: 20px; font-weight: 600; }
.hero-value.none { color: var(--eic-fg2); }
.sub { font-size: 12px; color: var(--eic-fg2); }
.fig.rec { color: var(--eic-rec); font-weight: 700; }
.fig.pred { color: var(--eic-pred); font-weight: 700; text-decoration: underline dashed; text-underline-offset: 3px; }
.block { margin: 10px 0; }
.row { display: flex; flex-wrap: wrap; gap: 2px 10px; padding: 5px 0; border-bottom: 1px solid var(--eic-line); }
.row .lbl { flex: 1 1 10em; color: var(--eic-fg2); }
.row .val { flex: 1 1 12em; text-align: right; }
.row .blockers { flex-basis: 100%; }
.none { color: var(--eic-fg2); }
.band, .conf, .muted { color: var(--eic-fg2); font-size: 12px; }
.band { display: block; }
.blockers { margin: 4px 0 0; padding-left: 18px; font-size: 12px; color: var(--eic-fg2); }
ul { margin: 2px 0 6px; padding-left: 18px; }
code { font-family: ui-monospace, Consolas, monospace; font-size: 12px; }
details { margin: 8px 0; border: 1px solid var(--eic-line); border-radius: 8px; padding: 4px 10px; }
details summary { cursor: pointer; font-weight: 600; padding: 2px 0; }
details h4 { margin: 8px 0 2px; font-size: 12px; text-transform: uppercase; color: var(--eic-fg2); }
.history { border-style: dashed; }
.ftr { display: flex; flex-wrap: wrap; gap: 4px 16px; margin-top: 8px; font-size: 12px; color: var(--eic-fg2); }
.ftr p { flex-basis: 100%; margin: 0; }
summary:focus-visible { outline: 2px solid var(--eic-pred); outline-offset: 2px; }
@container (min-width: 560px) {
  .grid { display: grid; grid-template-columns: 1fr 1fr; column-gap: 18px; }
  .grid h3 { grid-column: 1 / -1; }
}
@media (forced-colors: active) { .badge, .pill, .hero, .callout { border-color: CanvasText; } }
`;

// ===========================================================================
// 6. the custom element
// ===========================================================================
const Base = typeof HTMLElement !== 'undefined' ? HTMLElement : class {};

export class EccoIntelligenceCard extends Base {
  constructor() {
    super();
    this._config = null;
    this._hass = null;
    this._fp = null;
    this._timer = null;
    this._env = makeFormatters();
    this._now = () => Date.now();
    this._root = typeof this.attachShadow === 'function' ? this.attachShadow({ mode: 'open' }) : null;
  }

  static getStubConfig() {
    return { type: `custom:${TAG}` };
  }

  setConfig(config) {
    this._config = validateConfig(config);
    this._fp = null;
    this._render();
  }

  getCardSize() {
    return 9;
  }

  getGridOptions() {
    return { columns: 'full', rows: 'auto', min_columns: 6 };
  }

  get hass() {
    return this._hass;
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._config) return;
    const fp = this._fingerprint();
    if (this._fp && fp.length === this._fp.length && fp.every((st, i) => st === this._fp[i])) return;
    this._fp = fp;
    this._render();
  }

  connectedCallback() {
    if (this._timer === null) this._timer = setInterval(() => this._render(), TICK_MS);
    this._render();
  }

  disconnectedCallback() {
    if (this._timer !== null) clearInterval(this._timer);
    this._timer = null;
  }

  _states() {
    const h = this._hass;
    return h && h.states && typeof h.states === 'object' ? h.states : {};
  }

  /** The configured entities' state objects: Home Assistant replaces a state object whenever its state or an attribute
   * changes, so identity is the change test (no serialisation of attributes on every hass update). */
  _fingerprint() {
    const s = this._states();
    return Object.values(this._config.entities).map((id) => s[id]);
  }

  _render() {
    if (!this._root || !this._config) return;
    const open = new Set();
    for (const d of this._root.querySelectorAll('details[data-k]')) {
      if (d.hasAttribute('open')) open.add(d.getAttribute('data-k'));
    }
    const vm = deriveModel(this._states(), this._config.entities, this._now());
    this._root.innerHTML = `<style>${STYLE}</style>${renderCard(vm, this._config, this._env, open)}`;
  }
}

// The only import-time side effect: register the element and the card picker entry.
if (typeof customElements !== 'undefined' && typeof HTMLElement !== 'undefined') {
  if (!customElements.get(TAG)) customElements.define(TAG, EccoIntelligenceCard);
  if (typeof window !== 'undefined') {
    window.customCards = window.customCards || [];
    if (!window.customCards.some((c) => c && c.type === TAG)) {
      window.customCards.push({
        type: TAG,
        name: 'ECCO Intelligence Card',
        description: 'Read-only ECCO Intelligence SHADOW advice: status, next charge target or why there is none, forecasts with ranges, data quality and the open decisions. Applies nothing.',
        preview: false,
      });
    }
  }
}
