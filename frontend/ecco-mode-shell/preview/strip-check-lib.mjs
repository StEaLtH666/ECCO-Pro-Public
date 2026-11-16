// The judging half of the headless-browser check of the alert strip (review round 3). Pure functions, no DOM and no browser, so the logic of the check is itself
// tested offline (test/strip-check.test.mjs) with synthetic measurements, including measurements of a strip that has been hidden in every way the reviewers found.
//
// The measuring half is preview/strip-check.html: it renders the real card in Production and Geek Mode, light and dark, with and without Home Assistant's theme
// variables, at two widths, and reports what the browser computed (getComputedStyle, getBoundingClientRect, elementsFromPoint, Range boxes). It never reads the
// stylesheet. This file decides, from those numbers, whether a person looking at the screen could see and read the strip.

/** A colour as the browser reports it: "rgb(1, 2, 3)", "rgba(1, 2, 3, 0.5)", "rgb(1 2 3 / 50%)", "color(srgb 0.1 0.2 0.3 / 0.5)". null when unreadable. */
export function parseColour(text) {
  if (typeof text !== 'string') return null;
  const t = text.trim().toLowerCase();
  if (t === 'transparent') return { r: 0, g: 0, b: 0, a: 0 };
  let m = /^rgba?\(\s*([\d.]+)(%?)[\s,]+([\d.]+)(%?)[\s,]+([\d.]+)(%?)(?:\s*[,/]\s*([\d.]+)(%?))?\s*\)$/.exec(t);
  if (m) {
    const ch = (v, pct) => Math.max(0, Math.min(255, pct ? (Number(v) * 255) / 100 : Number(v)));
    return { r: ch(m[1], m[2]), g: ch(m[3], m[4]), b: ch(m[5], m[6]), a: m[7] === undefined ? 1 : Math.max(0, Math.min(1, m[8] ? Number(m[7]) / 100 : Number(m[7]))) };
  }
  m = /^color\(\s*srgb\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)(?:\s*\/\s*([\d.]+)(%?))?\s*\)$/.exec(t);
  if (m) return { r: Number(m[1]) * 255, g: Number(m[2]) * 255, b: Number(m[3]) * 255, a: m[4] === undefined ? 1 : m[5] ? Number(m[4]) / 100 : Number(m[4]) };
  return null;
}

/** `top` painted over `bottom` (both { r, g, b, a }). */
export function over(top, bottom) {
  const a = top.a + bottom.a * (1 - top.a);
  if (a <= 0) return { r: 0, g: 0, b: 0, a: 0 };
  const c = (t, b) => (t * top.a + b * bottom.a * (1 - top.a)) / a;
  return { r: c(top.r, bottom.r), g: c(top.g, bottom.g), b: c(top.b, bottom.b), a };
}

/** WCAG 2 relative luminance of an opaque colour. */
export function luminance({ r, g, b }) {
  const f = (v) => {
    const s = v / 255;
    return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
}

/** WCAG 2 contrast ratio between two opaque colours (1 to 21). */
export function contrastRatio(a, b) {
  const la = luminance(a);
  const lb = luminance(b);
  return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05);
}

/** The colour behind a piece of text: the background colours of the element and its ancestors (nearest first) painted over each other and over the canvas. */
export function effectiveBackground(layers, canvas = { r: 255, g: 255, b: 255, a: 1 }) {
  let acc = canvas;
  for (let i = layers.length - 1; i >= 0; i -= 1) {
    const c = typeof layers[i] === 'string' ? parseColour(layers[i]) : layers[i];
    if (c) acc = over(c, acc);
  }
  return acc;
}

const TOL = 0.75;
const inside = (inner, outer) => inner.left >= outer.left - TOL && inner.right <= outer.right + TOL && inner.top >= outer.top - TOL && inner.bottom <= outer.bottom + TOL;
const rectOf = (r) => ({ left: r.x, top: r.y, right: r.x + r.width, bottom: r.y + r.height, width: r.width, height: r.height });
const num = (v) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const px = (s) => {
  const m = /^(-?[\d.]+)px$/.exec(String(s));
  return m ? Number(m[1]) : null;
};

/** What an ancestor (or the strip) may not do to the strip. Each is the browser's computed value: "none" is a computed value, not an absence. */
const NEUTRAL = Object.freeze({ transform: 'none', rotate: 'none', scale: 'none', translate: 'none', filter: 'none', clipPath: 'none', maskImage: 'none', backdropFilter: 'none' });

/** Attributes that shut a subtree out of the accessibility tree, whatever their value (aria-hidden="false" is still a decision nobody made). */
const A11Y_BLOCKERS = Object.freeze(['aria-hidden', 'inert', 'hidden']);
const present = (v) => v !== null && v !== undefined;

/**
 * The checks for one measured state. A state is { id, scenario, theme, vars, mode, width, viewport, host, shell, strip, alerts, bodies }, as built by
 * strip-check.html. Returns [{ name, ok, detail }] (every check is reported, so a pass shows what was looked at).
 */
export function evaluateState(m) {
  const out = [];
  const add = (name, ok, detail = '') => out.push({ name, ok: Boolean(ok), detail: ok ? '' : String(detail) });
  const s = m.strip;
  add('the strip exists in the shell', s && s.present === true, 'no element with data-ecco-alert-strip');
  if (!s || s.present !== true) return out;
  const box = rectOf(s.rect);
  add('the shell is in the mode that was asked for (the check is not vacuous)', m.shell && m.shell.mode === m.mode, `data-mode is ${m.shell && m.shell.mode}, expected ${m.mode}`);
  add('the strip box has a real width and height', box.width >= 100 && box.height >= 16, `${box.width.toFixed(1)} x ${box.height.toFixed(1)} px`);
  add('the strip box is inside the viewport', inside(box, { left: 0, top: 0, right: m.viewport.w, bottom: m.viewport.h }), `box ${JSON.stringify(s.rect)} in a ${m.viewport.w} x ${m.viewport.h} viewport`);
  const host = rectOf(m.host);
  add('the strip box is inside its card (the host element)', inside(box, host), `box ${JSON.stringify(s.rect)} outside host ${JSON.stringify(m.host)}`);
  add('the strip is in the same column as the card, not shifted sideways', Math.abs(box.left - host.left) <= 40 && Math.abs(box.right - host.right) <= 40, `left ${box.left - host.left}, right ${box.right - host.right} against the host`);

  const chain = s.chain || [];
  const bad = (pred) => chain.filter(pred).map((c) => `${c.tag}${c.cls ? `.${c.cls}` : ''}`);
  const hidden = bad((c) => c.display === 'none' || c.visibility !== 'visible' || (c.contentVisibility && c.contentVisibility !== 'visible'));
  add('the strip and everything around it is displayed and visible (display, visibility, content-visibility)', hidden.length === 0, hidden.join(', '));
  let op = 1;
  for (const c of chain) op *= num(c.opacity) === null ? 0 : c.opacity;
  add('the strip is fully opaque: opacity 1 on it and on every ancestor', op >= 0.995, `effective opacity ${op.toFixed(3)}`);
  for (const [prop, neutral] of Object.entries(NEUTRAL)) {
    const moved = bad((c) => c[prop] !== neutral && c[prop] !== undefined && c[prop] !== '' && c[prop] !== 'normal');
    add(`no ${prop} on the strip or any ancestor`, moved.length === 0, moved.join(', '));
  }
  const clipped = [];
  for (const c of chain) {
    if (!c.rect || c.isHost || c.tag === 'html' || c.tag === 'body') continue;
    if ((c.overflowX !== 'visible' || c.overflowY !== 'visible') && !inside(box, rectOf(c.rect))) clipped.push(`${c.tag}.${c.cls}`);
  }
  add('no ancestor clips the strip: where an ancestor hides overflow the strip box lies inside it', clipped.length === 0, clipped.join(', '));
  const contained = bad((c) => c.contain && c.contain !== 'none' && /size|paint|strict|content/.test(c.contain));
  add('no size or paint containment on the strip or its ancestors', contained.length === 0, contained.join(', '));

  // review round 4 (reviewer mutants J2 and J5): what a screen reader gets. An attribute that is absent is null; a chain entry with no `a11y` was not measured, which fails.
  const unmeasured = bad((c) => !c.a11y);
  const shutOut = bad((c) => c.a11y && A11Y_BLOCKERS.some((k) => present(c.a11y[k])));
  add('assistive technology is not shut out: no aria-hidden, inert or hidden attribute (of any value) on the strip or on any ancestor, in the shell, the host or the page',
    unmeasured.length === 0 && shutOut.length === 0, unmeasured.length ? `not measured: ${unmeasured.join(', ')}` : shutOut.map((x) => `${x} hides it`).join(', '));
  const sa = s.a11y || null;
  add('the strip is a labelled region announced politely: role region, aria-live polite, a label of at least 5 characters',
    sa && sa.role === 'region' && sa['aria-live'] === 'polite' && typeof sa['aria-label'] === 'string' && sa['aria-label'].trim().length >= 5,
    `role ${sa && sa.role}, aria-live ${sa && sa['aria-live']}, label ${JSON.stringify(sa && sa['aria-label'])}`);
  add('the strip is not muted by aria-busy or aria-relevant', sa && !present(sa['aria-busy']) && !present(sa['aria-relevant']), `aria-busy ${sa && sa['aria-busy']}, aria-relevant ${sa && sa['aria-relevant']}`);

  const al = m.alerts || [];
  add('the strip shows at least one line (an alert or the quiet "no active alerts" line)', al.length >= 1, 'the strip is empty');
  if (m.expectAlerts !== undefined && m.expectAlerts !== null) add(`the strip shows ${m.expectAlerts} alert line(s) (the alerts the data calls for)`, al.filter((a) => !a.quiet).length === m.expectAlerts, `${al.filter((a) => !a.quiet).length} shown`);
  for (const a of al) {
    const who = `${a.quiet ? 'the quiet line' : `alert ${a.id}`} (${a.part || 'text'})`;
    const t = a.textBox ? rectOf(a.textBox) : null;
    add(`${who}: its text has a box with a real size, inside the strip`, t && t.width >= 8 && t.height >= 8 && inside(t, box), `text box ${JSON.stringify(a.textBox)} in strip ${JSON.stringify(s.rect)}`);
    const fs = px(a.fontSize);
    add(`${who}: the font is at least 12 px`, fs !== null && fs >= 12, `font-size ${a.fontSize}`);
    const lh = px(a.lineHeight);
    add(`${who}: the line height is normal or at least the font size`, a.lineHeight === 'normal' || (lh !== null && fs !== null && lh >= fs), `line-height ${a.lineHeight}`);
    const fill = parseColour(a.textFill || a.color);
    const col = parseColour(a.color);
    add(`${who}: the text colour is opaque (colour and text fill)`, col && fill && col.a >= 0.99 && fill.a >= 0.99, `color ${a.color}, fill ${a.textFill}`);
    if (col) {
      const bg = effectiveBackground(a.bgLayers || []);
      const ratio = contrastRatio(over(col, bg), bg);
      add(`${who}: the text contrast against its background is at least 4.5 : 1`, ratio >= 4.5, `${ratio.toFixed(2)} : 1 (text ${a.color} on ${JSON.stringify(a.bgLayers)})`);
    }
    if (a.icon) {
      const ic = parseColour(a.icon.color);
      const ir = a.icon.rect ? rectOf(a.icon.rect) : null;
      add(`${who}: the severity icon has a box with a real size, inside the strip`, ir && ir.width >= 12 && ir.height >= 12 && inside(ir, box), `icon box ${JSON.stringify(a.icon.rect)}`);
      if (ic) {
        const bg = effectiveBackground(a.bgLayers || []);
        const ratio = contrastRatio(over(ic, bg), bg);
        add(`${who}: the icon is opaque and at least 3 : 1 against its background`, ic.a >= 0.99 && ratio >= 3, `${ratio.toFixed(2)} : 1 (icon ${a.icon.color})`);
      }
    }
    add(`${who}: nothing covers it (the element at its centre is inside the strip)`, a.hit && a.hit.inside === true, `the top element there is ${a.hit && a.hit.tag}`);
    add(`${who}: it has text`, typeof a.text === 'string' && a.text.trim().length >= 3, `text ${JSON.stringify(a.text)}`);
    if (a.part === 'head') {
      // a critical alert is role alert, any other alert is role status, the quiet line is plain text; none of them is hidden from assistive technology
      const want = a.quiet ? null : a.severity === 'critical' ? 'alert' : 'status';
      const got = a.role === undefined ? undefined : a.role;
      add(`${who}: its role is ${want === null ? 'none (the quiet line is plain text)' : want} and it is not hidden from assistive technology`,
        got !== undefined && got === want && a.lineA11y && !A11Y_BLOCKERS.some((k) => present(a.lineA11y[k])), `role ${JSON.stringify(got)}, attributes ${JSON.stringify(a.lineA11y)}`);
    }
  }
  const b = m.bodies || {};
  if (m.mode === 'geek') {
    add('Geek Mode: the Geek body is shown and the Production body is hidden', b.geek && b.geek.shown === true && b.production && b.production.shown === false, JSON.stringify(b));
    add('Geek Mode: the strip is above the Geek body (it is not pushed below it)', b.geek && b.geek.rect && box.bottom <= rectOf(b.geek.rect).top + TOL, `strip bottom ${box.bottom}, Geek top ${b.geek && b.geek.rect && b.geek.rect.y}`);
  } else {
    add('Production Mode: the Production body is shown and the Geek body is hidden', b.production && b.production.shown === true && b.geek && b.geek.shown === false, JSON.stringify(b));
    add('Production Mode: the strip is above the Production body', b.production && b.production.rect && box.bottom <= rectOf(b.production.rect).top + TOL, `strip bottom ${box.bottom}, Production top ${b.production && b.production.rect && b.production.rect.y}`);
  }
  return out;
}

/** The strip must be the same box, with the same lines in the same places, in both modes. Returns [{ name, ok, detail }]. */
export function compareModes(prod, geek) {
  const out = [];
  const add = (name, ok, detail = '') => out.push({ name, ok: Boolean(ok), detail: ok ? '' : String(detail) });
  const same = (a, b) => ['x', 'y', 'width', 'height'].every((k) => Math.abs(a[k] - b[k]) <= TOL);
  const p = prod.strip && prod.strip.rect;
  const g = geek.strip && geek.strip.rect;
  add('the strip is the same box in both modes (position and size)', p && g && same(p, g), `Production ${JSON.stringify(p)}, Geek ${JSON.stringify(g)}`);
  const pa = prod.alerts || [];
  const ga = geek.alerts || [];
  add('the strip shows the same lines in both modes (count and text)', pa.length === ga.length && pa.every((a, i) => a.text === ga[i].text && a.id === ga[i].id), `Production ${pa.length}, Geek ${ga.length}`);
  add('and each line is the same box in both modes', pa.length === ga.length && pa.every((a, i) => a.textBox && ga[i].textBox && same(a.textBox, ga[i].textBox)), 'a line moved or changed size between the modes');
  // review round 4: the accessibility attributes are identical in both modes, on the strip, on everything around it and on every line (so a mode-dependent aria-hidden,
  // aria-live, role or label is a failure even where each mode alone looks acceptable)
  const ps = prod.strip || {};
  const gs = geek.strip || {};
  const js = (v) => JSON.stringify(v === undefined ? null : v);
  add('the strip carries the same accessibility attributes in both modes (role, aria-live, label, aria-hidden, inert, hidden ...)', ps.a11y !== undefined && js(ps.a11y) === js(gs.a11y), `Production ${js(ps.a11y)}, Geek ${js(gs.a11y)}`);
  add('and so does everything around the strip (the shell, the host, the page)', Array.isArray(ps.chain) && js((ps.chain || []).map((c) => c.a11y)) === js((gs.chain || []).map((c) => c.a11y)), 'an ancestor of the strip has other accessibility attributes in the other mode');
  add('and every alert line has the same role and attributes in both modes', pa.length === ga.length && pa.every((a, i) => a.role === ga[i].role && js(a.lineA11y) === js(ga[i].lineA11y)), 'a line has another role or attributes in the other mode');
  return out;
}

/**
 * Review round 9: the strip must be the same strip once everything the card scheduled has run. `first` was measured in the same task as the switch or the render, `later` after a zero-delay timer, the microtasks it leaves and up to two animation
 * frames (strip-check.html; in a headless run the frames mostly do not come, round 10). A card that hides, empties, moves or mutes the strip a moment later (a promise continuation, an async function, a timer, a frame, an observer callback: reviewer mutants E05 and E08) passes
 * every check on `first` and fails here. Returns [{ name, ok, detail }].
 */
export function compareSettled(first, later) {
  const out = [];
  const add = (name, ok, detail = '') => out.push({ name, ok: Boolean(ok), detail: ok ? '' : String(detail) });
  const same = (a, b) => ['x', 'y', 'width', 'height'].every((k) => Math.abs(a[k] - b[k]) <= TOL);
  const js = (v) => JSON.stringify(v === undefined ? null : v);
  const f = first.strip || {};
  const s = later.strip || {};
  add('once everything scheduled has run, the strip is still there', f.present === true && s.present === true, `before ${f.present}, after ${s.present}`);
  add('the strip is the same box once everything scheduled has run (position and size)', f.rect && s.rect && same(f.rect, s.rect), `before ${js(f.rect)}, after ${js(s.rect)}`);
  const fa = first.alerts || [];
  const sa = later.alerts || [];
  add('the strip shows the same lines once everything scheduled has run (count, id and text)', fa.length === sa.length && fa.every((a, i) => a.text === sa[i].text && a.id === sa[i].id && a.part === sa[i].part), `before ${fa.length} lines, after ${sa.length}`);
  add('and each line is the same box', fa.length === sa.length && fa.every((a, i) => a.textBox && sa[i].textBox && same(a.textBox, sa[i].textBox)), 'a line moved or changed size');
  add('the strip says the same number of alerts (data-alert-count)', f.count === s.count, `before ${f.count}, after ${s.count}`);
  add('the strip carries the same accessibility attributes once everything scheduled has run (role, aria-live, label, aria-hidden, inert, hidden ...)', f.a11y !== undefined && js(f.a11y) === js(s.a11y), `before ${js(f.a11y)}, after ${js(s.a11y)}`);
  add('and so does everything around the strip (the shell, the host, the page)', Array.isArray(f.chain) && js((f.chain || []).map((c) => c.a11y)) === js((s.chain || []).map((c) => c.a11y)), 'an ancestor of the strip has other accessibility attributes later');
  add('and every alert line has the same role and attributes', fa.length === sa.length && fa.every((a, i) => a.role === sa[i].role && js(a.lineA11y) === js(sa[i].lineA11y)), 'a line has another role or attributes later');
  add('the same mode is shown, with the same bodies shown and hidden', first.shell && later.shell && first.shell.mode === later.shell.mode && js(first.bodies && Object.fromEntries(Object.entries(first.bodies).map(([k, b]) => [k, b && b.shown]))) === js(later.bodies && Object.fromEntries(Object.entries(later.bodies).map(([k, b]) => [k, b && b.shown]))), `before ${js(first.shell)}, after ${js(later.shell)}`);
  return out;
}

const phaseOf = (m) => (m && m.phase === 'settled' ? 'settled' : 'immediate');

/**
 * Group a flat list of measured states into the report: { states: [{ id, checks }], pairs: [{ id, checks }], failed: n, total: n }. Production is paired with Geek (in each phase), and, from round 9, every
 * measurement made in the same task as the action is paired with its twin made after everything scheduled had run. With `requireSettled`, a measurement without its twin (or no twin at all) is a failure: a page that
 * forgot to wait cannot pass.
 */
export function evaluateAll(measured, { requireSettled = false } = {}) {
  const states = measured.map((m) => ({ id: m.id, checks: evaluateState(m) }));
  const key = (m) => [m.scenario, m.theme, m.vars, m.width, m.viewport.w, phaseOf(m)].join('|');
  const prod = new Map();
  const geek = new Map();
  for (const m of measured) (m.mode === 'geek' ? geek : prod).set(key(m), m);
  const pairs = [];
  for (const [k, p] of prod) {
    const g = geek.get(k);
    pairs.push({ id: `${k} (Production against Geek)`, checks: g ? compareModes(p, g) : [{ name: 'the other mode was measured', ok: false, detail: 'missing' }] });
  }
  for (const k of geek.keys()) if (!prod.has(k)) pairs.push({ id: `${k} (Production against Geek)`, checks: [{ name: 'the other mode was measured', ok: false, detail: 'missing' }] });
  // the same strip once everything scheduled has run
  const modeKey = (m) => [m.scenario, m.theme, m.vars, m.width, m.viewport.w, m.mode].join('|');
  const first = new Map();
  const later = new Map();
  for (const m of measured) (phaseOf(m) === 'settled' ? later : first).set(modeKey(m), m);
  if (requireSettled || later.size > 0) {
    for (const [k, a] of first) {
      const b = later.get(k);
      pairs.push({ id: `${k} (immediately against after everything scheduled has run)`, checks: b ? compareSettled(a, b) : [{ name: 'the strip was measured again after everything scheduled had run', ok: false, detail: 'missing' }] });
    }
    for (const k of later.keys()) if (!first.has(k)) pairs.push({ id: `${k} (immediately against after everything scheduled has run)`, checks: [{ name: 'the strip was measured in the same task as the action', ok: false, detail: 'missing' }] });
  }
  const all = [...states, ...pairs].flatMap((x) => x.checks);
  return { states, pairs, failed: all.filter((c) => !c.ok).length, total: all.length };
}
