// Feeds a JSON map {b9 text: expected kind} (written by registry/tests/test_fallback_recovery_dashboard.py from the
// firmware mirror's own text builders) through the card and reports what the card made of each text. Not a test file.
import { readFileSync } from 'node:fs';
import { card, scenarios, IDS, cardRegexes, HAZARD_PATTERNS, NEVER_WORDS, renderScenario, allText } from './helpers.mjs';

const texts = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const patterns = [...cardRegexes().map((r) => r.re), ...HAZARD_PATTERNS, ...NEVER_WORDS];
const wrongState = [];
const hazards = [];
// FB-B2: the Save / Invalidate families keep the review state "available" (the review itself is not the thing that ended)
// and are classified by vm.act as <family>:<outcome>
const ACT_OF = {
  saveprogress: 'save:progress', saverefused: 'save:refused', saved: 'save:saved', savenotcommitted: 'save:notcommitted', saveunknown: 'save:unknown',
  invalidaterefused: 'invalidate:refused', invalidated: 'invalidate:invalidated', invalidatenotcommitted: 'invalidate:notcommitted',
  invalidateunknown: 'invalidate:unknown', actionrefused: 'other:refused',
};
for (const [t, kind] of Object.entries(texts)) {
  const E = { ...scenarios.idle_saved, last_result: t };
  const vm = card.deriveModel(E, IDS);
  const ok = { refused: ['refused'], cleared: ['cleared'], notcompleted: ['readerror', 'mismatch'], expired: ['expired'], internal: ['internal'], seed: ['available'], reading: ['available'], ready: ['available'] }[kind];
  if (ok && !ok.includes(vm.review)) wrongState.push([t, vm.review]);
  if (Object.hasOwn(ACT_OF, kind)) {
    const got = vm.act ? `${vm.act.family}:${vm.act.outcome}` : null;
    if (got !== ACT_OF[kind] || vm.review !== 'available') wrongState.push([t, `${vm.review}/${got}`]);
  }
  const r = renderScenario('idle_saved', { E });
  for (const s of allText(r.out, r.tv)) for (const re of patterns) if (re.test(s)) hazards.push([String(re), s.slice(0, 120)]);
}
process.stdout.write(JSON.stringify({ count: Object.keys(texts).length, wrongState, hazards }));
