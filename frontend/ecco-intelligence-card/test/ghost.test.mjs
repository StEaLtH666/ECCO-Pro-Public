// The optional Ghost section ("Advice versus reality"): driven by fixtures built by running intelligence/ghost_feed.py on a
// SYNTHETIC house (test/fixtures/ghost_*.json: {state, attributes} as to_entity_payload returns them). The section appears only
// when the optional Ghost entity exists; it never writes, never calls anything, and never puts attribute text into markup
// unescaped.
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { installDom } from './minidom.mjs';

installDom(); // BEFORE the card module is evaluated (the element tests below)
const mod = await import('../ecco-intelligence-card.js?ghost');
const { statesFor, nowFor, textOf, here, env } = await import('./helpers.mjs');
const { deriveGhost, deriveModel, renderCard, renderGhost, validateConfig, DEFAULT_GHOST_ENTITY, EccoIntelligenceCard } = mod;

const GID = DEFAULT_GHOST_ENTITY;
const fx = (name) => JSON.parse(readFileSync(path.join(here, 'fixtures', `${name}.json`), 'utf8'));
const MONEY = fx('ghost_money');
const NOMONEY = fx('ghost_nomoney');
const INSUFFICIENT = fx('ghost_insufficient');

function ghostState(doc, mutate = null, state = null) {
  const attributes = structuredClone(doc.attributes);
  if (mutate) mutate(attributes);
  return { entity_id: GID, state: state === null ? doc.state : state, attributes };
}
const withGhost = (st, base = 'synthetic_ok') => ({ ...statesFor(base), ...(st ? { [GID]: st } : {}) });
const cfg = validateConfig({});
function cardHtml(states, base = 'synthetic_ok') {
  const vm = deriveModel(states, cfg.entities, nowFor(base));
  vm.ghost = deriveGhost(states, cfg.ghost);
  return renderCard(vm, cfg, env, new Set());
}
const section = (html) => {
  const i = html.indexOf('<section class="block ghost"');
  return i < 0 ? '' : html.slice(i, html.indexOf('</section>', i) + 10);
};
const ghostHtml = (st) => section(cardHtml(withGhost(st)));
const MONEY_P = /[+-]?\d+(?:\.\d+)?\s*p\b|£/;

test('fixtures: built by ghost_feed, flat attributes under the Ghost schema, small, with the SHADOW markers', () => {
  for (const d of [MONEY, NOMONEY, INSUFFICIENT]) {
    assert.equal(d.attributes.schema, 'ecco-intel-ghost-feed/1');
    assert.equal(d.attributes.simulated, true);
    assert.equal(d.attributes.intelligence_controlled_nothing, true);
    assert.equal(d.attributes.mode, 'SHADOW');
    assert.equal(d.attributes.applies_nothing, true);
    assert.equal(d.attributes.kind, 'ghost');
    assert.ok(JSON.stringify(d.attributes).length < 8192);
  }
  assert.equal(MONEY.attributes.money_available, true);
  assert.equal(NOMONEY.attributes.money_available, false);
  assert.equal(MONEY.attributes.days.length, 7);
});

test('absent entity: nothing is rendered and the card is byte-for-byte what it was', () => {
  const states = statesFor('synthetic_ok');
  assert.equal(deriveGhost(states, GID), null);
  const vm = deriveModel(states, cfg.entities, nowFor('synthetic_ok'));
  const without = renderCard(vm, cfg, env, new Set());
  vm.ghost = deriveGhost(states, GID);
  assert.equal(renderCard(vm, cfg, env, new Set()), without);
  assert.ok(!without.includes('ghost'));
  assert.ok(!without.includes('Ghost'));
  assert.equal(renderGhost(null), '');
  assert.equal(renderGhost(undefined), '');
});

test('banner: a simulation, Intelligence controlled nothing, evidence for the assisted decision and not a decision', () => {
  const html = ghostHtml(ghostState(MONEY));
  const banner = textOf(html.slice(html.indexOf('data-ghost="banner"'), html.indexOf('</p>', html.indexOf('data-ghost="banner"'))));
  assert.match(banner, /SIMULATION/);
  assert.match(banner, /Intelligence controlled nothing/);
  assert.match(banner, /evidence for the assisted-mode decision, not a decision/);
  assert.match(html, /role="note"/);
  assert.match(textOf(html), /Advice versus reality \(Ghost\)/);
});

test('scoreboard: one row per day, ahead and behind each in words and glyphs, behind as plain as ahead', () => {
  const html = ghostHtml(ghostState(MONEY));
  const rows = [...html.matchAll(/<li class="gday" data-gday="([^"]+)">([\s\S]*?)<\/li>/g)];
  assert.equal(rows.length, 7);
  const by = Object.fromEntries(rows.map((m) => [m[1], textOf(m[2])]));
  assert.match(by['2030-01-11'], /▲ ahead \+15\.7 p/);
  assert.match(by['2030-01-14'], /▼ behind -57\.7 p/);
  assert.match(by['2030-01-15'], /▼ behind -44\.6 p/);
  assert.match(by['2030-01-10'], /= level 0\.0 p/);
  const ahead = rows.filter((m) => /▲ ahead/.test(textOf(m[2]))).length;
  const behind = rows.filter((m) => /▼ behind/.test(textOf(m[2]))).length;
  assert.deepEqual([ahead, behind], [3, 3]);
  // the bars are decoration and hidden from assistive technology; the text carries every figure
  for (const m of rows) assert.match(m[2], /class="gtrack" aria-hidden="true"/);
  // behind bars sit left of the middle, ahead bars right
  const left = (d) => /<span class="ghalf neg"><span class="gbar/.test(rows.find((m) => m[1] === d)[2]);
  const right = (d) => /<span class="ghalf pos"><span class="gbar/.test(rows.find((m) => m[1] === d)[2]);
  assert.ok(left('2030-01-14') && !right('2030-01-14'));
  assert.ok(right('2030-01-11') && !left('2030-01-11'));
  assert.ok(!left('2030-01-10') && !right('2030-01-10'));
  // the longest bar is the worst day
  const width = (d) => Number(/style="width:(\d+)%"/.exec(rows.find((m) => m[1] === d)[2])[1]);
  assert.equal(width('2030-01-14'), 100);
  assert.ok(width('2030-01-15') < 100 && width('2030-01-15') > width('2030-01-11'));
});

test('headline, baseline and uncertainty: shown next to the week figure; the verdict says whether it is within the noise', () => {
  const html = ghostHtml(ghostState(MONEY));
  const t = textOf(html);
  assert.match(t, /Whole week, Ghost minus actual ▼ behind -90\.0 p/);
  assert.match(t, /Realised -52\.6 p, closing battery stock/);
  assert.match(t, /No-advice model baseline 0\.0 p/);
  assert.match(t, /Closing battery stock valued two ways: \+1\.4 p and 0\.0 p/);
  assert.match(t, /round-trip efficiency were 78%: -109\.2 p/);
  assert.match(t, /round-trip efficiency were 81%: -90\.0 p/);
  assert.match(t, /round-trip efficiency were 84%: -90\.0 p/);
  assert.match(html, /data-ghost="verdict" data-within="no"/);
  assert.match(t, /Larger than the model's own uncertainty/);
  // a small difference is visibly within the noise
  const small = withGhost(ghostState(MONEY, (a) => { a.ready_for_assisted_evidence.delta_stock_adjusted_p = 4.0; }));
  const st = textOf(section(cardHtml(small)));
  assert.match(st, /Whole week, Ghost minus actual ▲ ahead \+4\.0 p/);
  assert.match(section(cardHtml(small)), /data-ghost="verdict" data-within="yes"/);
  assert.match(st, /Within the noise: this difference is no bigger than the model's own uncertainty/);
  // and a baseline that is not zero widens the noise
  const base = withGhost(ghostState(MONEY, (a) => {
    a.ready_for_assisted_evidence.delta_stock_adjusted_p = 30;
    a.ready_for_assisted_evidence.model_baseline_delta_p = -35;
  }));
  assert.match(section(cardHtml(base)), /data-within="yes"/);
});

test('battery story per day: low points against the reserve, a breach marked in words and glyph, advice followed or not with reasons', () => {
  const html = ghostHtml(ghostState(MONEY));
  const day = (d, h = html) => textOf(new RegExp(`<li class="gday" data-gday="${d}">[\\s\\S]*?</li>`).exec(h)[0]);
  assert.match(day('2030-01-10'), /Battery low point: actual 40%, Ghost 40%, reserve 40%/);
  assert.match(day('2030-01-10'), /✓ Ghost stayed at or above the reserve/);
  assert.match(day('2030-01-10'), /Advice: 1 followed/);
  assert.match(day('2030-01-12'), /1 not followed: the advice was blocked \(nothing to follow\)/);
  assert.match(day('2030-01-15'), /1 not followed: it had no time window, so the Ghost could not act on it/);
  assert.match(day('2030-01-16'), /Advice: no advice recorded/);
  // a ghost breach
  const breach = ghostHtml(ghostState(MONEY, (a) => {
    const d = a.days.find((x) => x.date === '2030-01-14');
    d.ghost_below_reserve = true;
    d.ghost_min_soc_pct = 31.5;
    a.ready_for_assisted_evidence.ghost_below_reserve_slots = 3;
    a.ready_for_assisted_evidence.ghost_below_reserve_days = 1;
  }));
  assert.match(day('2030-01-14', breach), /Ghost 32%, reserve 40%/);
  assert.match(day('2030-01-14', breach), /▼ Ghost went BELOW the reserve/);
  assert.match(textOf(breach), /Reserve breaches: 1 days, 3 hourly slots with the Ghost below the reserve \(40%\)/);
  assert.ok(!/BELOW/.test(day('2030-01-13', breach)));
  // the SOC bars are decoration too
  assert.match(breach, /class="gsoc act" aria-hidden="true"/);
});

test('evidence block: days compared, share ahead, worst day, reserve breaches, data-quality flags, and a decides-nothing line', () => {
  const html = ghostHtml(ghostState(MONEY));
  const ev = textOf(html.slice(html.indexOf('data-ghost="evidence"')));
  assert.match(ev, /Evidence for the assisted decision/);
  assert.match(ev, /Days compared: 7/);
  assert.match(ev, /Days the Ghost was ahead: 3 of 7 \(43%\)/);
  assert.match(ev, /Days the Ghost was behind: 3, level: 1/);
  assert.match(ev, /Worst day for the Ghost: Mon 14 Jan, -57\.7 p|Worst day for the Ghost: Mon, 14 Jan, -57\.7 p|Worst day for the Ghost: .*14 Jan.*-57\.7 p/);
  assert.match(ev, /Reserve breaches: none, the Ghost never went below the reserve \(40%\)/);
  assert.match(ev, /Data quality/);
  assert.match(ev, /DUMP_ADVICE_HAS_NO_WINDOW/);
  assert.match(ev, /EXPORT_TARIFF_NOT_VERIFIED/);
  assert.match(ev, /Approximations: SOC: hourly means/);
  assert.match(ev, /This decides nothing\. Whether to move to assisted mode stays the owner's decision\./);
  assert.match(html, /data-ghost="decides"/);
  // flags are listed, and "no flags" is said plainly
  const flagged = ghostHtml(ghostState(MONEY, (a) => { a.data_quality.ghost_model_flags = ['ACTUAL_ENERGY_NOT_BALANCED']; }));
  assert.match(textOf(flagged), /ACTUAL_ENERGY_NOT_BALANCED/);
  const clean = ghostHtml(ghostState(MONEY, (a) => {
    a.data_quality = { ghost_model_flags: [], notes: [], approximations: [], unusable_by_reason: {} };
  }));
  assert.match(textOf(clean), /no data-quality flags/);
});

test('no verified tariff: behaviour only, no money anywhere in the section, and not even when pence keys are present', () => {
  const html = ghostHtml(ghostState(NOMONEY));
  assert.match(html, /data-money="no"/);
  const t = textOf(html);
  assert.match(t, /Behaviour only, no money \(no verified tariff\)/);
  assert.match(t, /extra grid import of the Ghost/);
  assert.doesNotMatch(t, MONEY_P);
  assert.doesNotMatch(t, /▲ ahead|▼ behind/);
  assert.match(t, /Battery low point: actual \d+%, Ghost \d+%/);
  assert.match(t, /Days the Ghost differed from the real day: \d+/);
  assert.match(t, /If the battery round-trip efficiency were 81%: \d+ slots below the reserve/);
  // an unverified feed that nevertheless carries pence keys: they are ignored
  const sneaky = ghostHtml(ghostState(NOMONEY, (a) => {
    for (const d of a.days) { d.delta_stock_adjusted_p = 99.9; d.advice_effect_p = 99.9; }
    a.ready_for_assisted_evidence.delta_stock_adjusted_p = 99.9;
    a.ready_for_assisted_evidence.days_ghost_ahead = 7;
    a.ready_for_assisted_evidence.worst_ghost_day = { date: '2030-01-14', delta_p: -99.9 };
    a.totals.delta_stock_adjusted_p = 99.9;
  }));
  assert.doesNotMatch(textOf(sneaky), MONEY_P);
  assert.doesNotMatch(sneaky, /99\.9/);
  assert.doesNotMatch(textOf(sneaky), /Days the Ghost was ahead|Worst day/);
});

test('too little data: the banner and one plain line, no comparison', () => {
  const html = ghostHtml(ghostState(INSUFFICIENT));
  assert.match(html, /data-ghost-kind="insufficient"/);
  const t = textOf(html);
  assert.match(t, /SIMULATION/);
  assert.match(t, /too little usable recorded data yet to compare a week/);
  assert.ok(!html.includes('data-gday'));
});

test('unavailable, unknown or malformed: one quiet line, never an exception', () => {
  const quiet = (st, label) => {
    let html = '';
    assert.doesNotThrow(() => { html = ghostHtml(st); }, label);
    assert.match(html, /data-ghost-kind="unavailable"/, label);
    assert.equal(textOf(html), 'Ghost not available', label);
  };
  quiet(ghostState(MONEY, null, 'unavailable'), 'unavailable');
  quiet(ghostState(MONEY, null, 'unknown'), 'unknown');
  quiet({ entity_id: GID, state: 'OK', attributes: {} }, 'no attributes');
  quiet({ entity_id: GID, state: 'OK' }, 'no attributes object');
  quiet(ghostState(MONEY, (a) => { a.schema = 'ecco-intel-ghost-feed/2'; }), 'newer schema');
  quiet(ghostState(MONEY, (a) => { a.mode = 'ASSISTED'; }), 'mode');
  quiet(ghostState(MONEY, (a) => { a.applies_nothing = false; }), 'applies_nothing');
  quiet(ghostState(MONEY, (a) => { a.applies_nothing = 'true'; }), 'applies_nothing text');
  quiet(ghostState(MONEY, (a) => { a.kind = 'status'; }), 'kind');
  quiet(ghostState(MONEY, (a) => { a.simulated = false; }), 'not simulated');
  quiet(ghostState(MONEY, (a) => { a.intelligence_controlled_nothing = false; }), 'controlled something');
  quiet(ghostState(MONEY, (a) => { a.status = 'OK2'; }), 'status text');
  quiet(ghostState(MONEY, null, 'BLOCKED'), 'state differs from status');
  quiet(ghostState(MONEY, (a) => { a.days = 'x'; }), 'days not a list');
  quiet(ghostState(MONEY, (a) => { a.days = []; }), 'no days');
  quiet(ghostState(MONEY, (a) => { a.days = [null, 3, 'x', { date: 'soon' }, { date: '2030-01-1' }]; }), 'no readable day');
  quiet(ghostState(MONEY, (a) => { a.ready_for_assisted_evidence = null; }), 'no evidence block');
  quiet(ghostState(MONEY, (a) => { delete a.ready_for_assisted_evidence; }), 'evidence block missing');
  quiet({ entity_id: GID, state: 'OK', attributes: null }, 'null attributes');
  // a getter that throws must not escape either
  const bad = ghostState(MONEY);
  Object.defineProperty(bad.attributes, 'days', { get() { throw new Error('boom'); }, enumerable: true });
  quiet(bad, 'throwing attribute');
});

test('odd values inside a well-formed feed degrade quietly (no figure), never throw', () => {
  const weird = ghostState(MONEY, (a) => {
    a.days[1].delta_stock_adjusted_p = 'lots';
    a.days[2].actual_min_soc_pct = null;
    a.days[3].ghost_min_soc_pct = Infinity;
    a.days[4].advice_not_followed = { BLOCKED: 'many', NO_WINDOW: -1, ODD: 2 };
    a.days[5].advice_followed = 1.5;
    a.days[6].hours = 18;
    a.uncertainty = 7;
    a.totals = [];
    a.data_quality = { ghost_model_flags: [1, null, 'OK_FLAG'], notes: 'text', unusable_by_reason: { missing_hour: 3, odd_code: 2, none: 0 } };
    a.ready_for_assisted_evidence.worst_ghost_day = { date: 'x', delta_p: 'y' };
    a.ready_for_assisted_evidence.days_compared = -2;
  });
  let html = '';
  assert.doesNotThrow(() => { html = ghostHtml(weird); });
  const t = textOf(html);
  assert.match(html, /data-ghost-kind="ok"/);
  assert.match(t, /no figure/);
  assert.match(t, /2 not followed: ODD/);
  assert.match(t, /OK_FLAG/);
  assert.match(t, /3 hours missing/);
  assert.match(t, /2 odd_code/);
  assert.match(t, /\(18 h compared\)/);
  assert.doesNotMatch(t, /NaN|undefined|Infinity|null/);
  // a fuzz over every top-level attribute: wrong types never throw
  const junk = [null, 'x', 7, -1, [], {}, [1, 2], { a: 1 }, true, NaN];
  for (const key of Object.keys(MONEY.attributes)) {
    for (const j of junk) {
      assert.doesNotThrow(() => ghostHtml(ghostState(MONEY, (a) => { a[key] = j; })), `${key}=${String(j)}`);
    }
  }
});

test('escaping: no attribute text reaches the markup unescaped (notes, flags, reasons, dates, approximations, advice codes)', () => {
  const evil = '<img src=x onerror=alert(1)>"\'&';
  const html = ghostHtml(ghostState(MONEY, (a) => {
    a.data_quality.notes = [evil];
    a.data_quality.ghost_model_flags = [evil];
    a.data_quality.approximations = [evil];
    a.data_quality.unusable_by_reason = { [evil]: 2 };
    a.days[0].advice_not_followed = { [evil]: 1 };
    a.days[1].date = '2030-01-11';
    a.days[2].date = `${evil}`;
  }));
  assert.ok(!html.includes('<img'));
  assert.ok(!/onerror=alert\(1\)>/.test(html.replace(/&lt;img src=x onerror=alert\(1\)&gt;/g, '')));
  assert.ok(html.includes('&lt;img src=x onerror=alert(1)&gt;&quot;&#39;&amp;'));
  assert.equal(textOf(html).includes(evil), true, 'the text is shown as text');
  assert.ok(!html.includes('data-gday="<'), 'an unreadable date drops the row');
  // every ${} text goes through esc(): the section holds only the tags the card itself writes
  const tags = new Set([...html.matchAll(/<\/?([a-z0-9]+)/g)].map((m) => m[1]));
  assert.deepEqual([...tags].sort(), ['code', 'div', 'h3', 'h4', 'li', 'p', 'section', 'span', 'strong', 'ul'].filter((t) => tags.has(t)).sort());
});

test('a day with its own hours (a short day, a clock change) says so', () => {
  const html = ghostHtml(ghostState(MONEY, (a) => { a.days[0].hours = 23; }));
  assert.match(textOf(html), /\(23 h compared\)/);
});

test('days the summary dropped to stay small are stated; only the newest fourteen days are drawn', () => {
  const dropped = textOf(ghostHtml(ghostState(MONEY, (a) => { a.days_dropped = 4; })));
  assert.match(dropped, /4 older days left out to keep the summary small/);
  const many = ghostHtml(ghostState(MONEY, (a) => {
    a.days = Array.from({ length: 20 }, (_v, i) => ({ ...a.days[0], date: `2030-02-${String(i + 1).padStart(2, '0')}` }));
  }));
  assert.equal([...many.matchAll(/data-gday=/g)].length, 14);
  assert.ok(many.includes('data-gday="2030-02-20"') && !many.includes('data-gday="2030-02-06"'));
});

test('where it appears: with the live card and with a null-status card, never in the not-recognised notice', () => {
  const live = cardHtml(withGhost(ghostState(MONEY)));
  assert.ok(live.indexOf('data-sec="ghost"') > live.indexOf('class="drill"'));
  assert.ok(live.indexOf('data-sec="ghost"') < live.indexOf('<footer'));
  const stale = cardHtml(withGhost(ghostState(MONEY), 'stale'), 'stale');
  assert.match(stale, /data-kind="null"/);
  assert.match(stale, /data-sec="ghost"/);
  const states = withGhost(ghostState(MONEY));
  states[cfg.entities.status] = { ...states[cfg.entities.status], attributes: { ...states[cfg.entities.status].attributes, mode: 'ASSISTED' } };
  const bad = cardHtml(states);
  assert.match(bad, /data-kind="not_recognised"/);
  assert.ok(!bad.includes('data-sec="ghost"'));
});

test('the existing card is untouched by the Ghost: every golden fixture renders the same with a Ghost entity beside it, plus the section', () => {
  for (const name of ['all_open_blocked', 'synthetic_ok', 'stale', 'paused', 'self_test_failed', 'starting']) {
    const plain = cardHtml(statesFor(name), name);
    const both = cardHtml(withGhost(ghostState(MONEY), name), name);
    assert.equal(both.replace(section(both), ''), plain, name);
  }
});

test('configuration: ghost_entity is optional, must be a sensor id, and may not repeat a contract entity or a prototype id', () => {
  assert.equal(validateConfig({}).ghost, 'sensor.ecco_intel_ghost');
  assert.equal(validateConfig({ ghost_entity: 'sensor.site_ghost' }).ghost, 'sensor.site_ghost');
  assert.throws(() => validateConfig({ ghost_entity: 'switch.ecco_intel_ghost' }), /ghost_entity must be a sensor/);
  assert.throws(() => validateConfig({ ghost_entity: 5 }), /ghost_entity/);
  assert.throws(() => validateConfig({ ghost_entity: 'sensor.ecco_intel_status' }), /repeats/);
  assert.throws(() => validateConfig({ ghost_entity: 'sensor.ecco_intelligence_ghost' }), /frozen V1 prototype/);
  assert.deepEqual(Object.keys(validateConfig({}).entities).length, 13, 'the contract entities are unchanged');
  const custom = validateConfig({ ghost_entity: 'sensor.site_ghost' });
  const states = { ...statesFor('synthetic_ok'), 'sensor.site_ghost': ghostState(MONEY) };
  assert.ok(deriveGhost(states, custom.ghost).kind === 'ok');
  assert.equal(deriveGhost(states, GID), null);
});

test('the element: renders the section from hass.states, reads hass.states only, calls nothing, re-renders when the Ghost changes', () => {
  const reads = [];
  const calls = [];
  const trap = (name) => (...args) => { calls.push([name, args]); return Promise.resolve(); };
  const states = withGhost(ghostState(MONEY));
  const target = { states, callService: trap('callService'), callWS: trap('callWS'), callApi: trap('callApi'), connection: {}, user: {} };
  const hass = new Proxy(target, { get: (t, p) => { reads.push(String(p)); return t[p]; } });
  const el = new EccoIntelligenceCard();
  el.setConfig({});
  el._now = () => nowFor('synthetic_ok');
  el.hass = hass;
  el.connectedCallback();
  el._render();
  try {
    assert.ok(el.shadowRoot.querySelector('[data-sec="ghost"]'));
    assert.equal(el.shadowRoot.querySelectorAll('li[data-gday]').length, 7);
    assert.deepEqual([...new Set(reads)], ['states']);
    assert.deepEqual(calls, []);
    // no control of any kind in the section
    const html = section(el.shadowRoot.innerHTML);
    assert.doesNotMatch(html, /<(button|input|select|textarea|a|form)\b|onclick|href=/i);
    const n0 = el.shadowRoot.writes;
    el.hass = { states: { ...states } };
    assert.equal(el.shadowRoot.writes, n0, 'nothing changed: no re-render');
    el.hass = { states: { ...states, [GID]: ghostState(NOMONEY) } };
    assert.equal(el.shadowRoot.writes, n0 + 1, 'the Ghost entity changed: re-render');
    assert.ok(el.shadowRoot.querySelector('[data-money="no"]'));
    el.hass = { states: statesFor('synthetic_ok') };
    assert.equal(el.shadowRoot.querySelector('[data-sec="ghost"]'), null, 'entity removed: the section is gone');
  } finally {
    el.disconnectedCallback();
  }
});

test('responsive and accessible by construction: container query, wrapping, forced-colours, text for every bar', () => {
  const style = mod.STYLE;
  assert.match(style, /@container \(min-width: 480px\)[\s\S]*\.grow/);
  assert.match(style, /\.gsub \{[^}]*flex-wrap: wrap/);
  assert.match(style, /\.gday \{/);
  assert.match(style, /forced-colors: active\)[^\n]*\.gbar/);
  assert.doesNotMatch(style, /\.grow \{[^}]*(?:width|min-width): *\d{3,}px/);
  const html = ghostHtml(ghostState(MONEY));
  // every colour class on a figure is paired with a glyph and a word in the same element
  for (const m of html.matchAll(/<span class="gtag (tone-(?:ok|bad))">([^<]*)<\/span>/g)) {
    assert.match(m[2], /[▲▼✓]/);
    assert.match(m[2], /ahead|behind|BELOW|stayed|breach|never/);
  }
});
