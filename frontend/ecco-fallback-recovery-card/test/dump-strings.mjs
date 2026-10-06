// Prints the card's register order, static wording and every rendered text as JSON. Not a test file
// (the test glob is test/*.test.mjs): registry/tests/test_fallback_recovery_dashboard.py runs it to
// scan the card's strings against the energy-actions card regexes.
import { card, scenarios, build, renderScenario, allText } from './helpers.mjs';

const texts = new Set();
const push = (o) => {
  if (typeof o === 'string') texts.add(o);
  else if (Array.isArray(o)) o.forEach(push);
  else if (o && typeof o === 'object') Object.values(o).forEach(push);
};
const { SENTENCE, WARNING_TEXT, KIND_TEXT, LD_TEXT, DF_TEXT, W_TEXT, RECOVERY_TILES, RAW_ROWS, REGS, CLASS_NAMES, FLOW_TEXT, GATE_LABEL } = card;
[SENTENCE, WARNING_TEXT, KIND_TEXT, LD_TEXT, DF_TEXT, W_TEXT, RECOVERY_TILES, RAW_ROWS, FLOW_TEXT, GATE_LABEL].forEach(push);
REGS.forEach((r) => texts.add(r.name));
for (const b1 of CLASS_NAMES) texts.add(card.unusableSentence(b1, 7));
// the "stored profile not trusted / not compared" texts: one sentence and one selector note per class, and both captions
for (const b1 of CLASS_NAMES) texts.add(card.untrustedSentence(b1));
for (const b1 of CLASS_NAMES) Object.values(card.savedSegmentNote({ profile: 'unusable', b1 })).forEach((t) => texts.add(t));
texts.add(card.notComparedNote(build('not_saveable_unreadable').vm));
texts.add(card.notComparedNote(build('ready_match', { E: { ...scenarios.ready_match, review_slots: scenarios.ready_match.review_slots.replace(/dx=\w+$/, 'dx=-') } }).vm));
for (const code of ['244X', 'PWRL1', 'PWRH2', 'SOCH3', 'SRCG4', 'MODE5', 'BITS6', 'HHMM1', '243X', 'ZZZ']) {
  texts.add(card.blockerText(code, { reg244: 0, reg243: 5, slots: [] }));
}
card.warningRows('W1,W2,W3,W4,W5,W6,W9', []).forEach((r) => texts.add(r.text));
for (const name of Object.keys(scenarios)) {
  for (const elapsedS of [0, 40, 119]) {
    const { out, tv } = renderScenario(name, { elapsedS, ui: { detailOpen: true } });
    allText(out, tv).forEach((t) => texts.add(t));
  }
}
// FB-B2: the guarded Save / Invalidate flow in every UI state (arm intent, arm pending, request on its way or unanswered)
const flowOf = (name, kind, state) => {
  const vm = build(name).vm;
  const f = card.makeFlow(kind, { id: kind === 'save' ? vm.reviewId : vm.idHex, effect: kind === 'save' ? card.saveEffect(vm) : null, vm, nowMs: 0, keys: { b9: 'b' } });
  return { ...f, state };
};
for (const [name, kind] of [['arm_on_ready', 'save'], ['arm_on_corrupt', 'save'], ['arm_on_first', 'save'], ['arm_on_no_candidate', 'invalidate']]) {
  for (const intent of ['save', 'invalidate']) {
    for (const state of [null, 'sent', 'running', 'timeout', 'unsure']) {
      for (const extra of [{}, { armPending: true }, { cancelling: true }]) {
        const ui = { detailOpen: true, intent, flow: state ? flowOf(name, kind, state) : null, ...extra };
        const { out, tv } = renderScenario(name, { elapsedS: 20, armOnS: 3, ui });
        allText(out, tv).forEach((t) => texts.add(t));
      }
    }
  }
}
process.stdout.write(JSON.stringify({
  regs: REGS.map((r) => r.reg),
  classes: Object.fromEntries(REGS.map((r) => [r.reg, r.cls])),
  scenarios: Object.keys(scenarios),
  texts: [...texts],
}));
