// Feeds a JSON list of obligation vectors (written by registry/tests/test_fallback_recovery_dashboard.py from the
// firmware mirror's own vector_text builder) through the card's strict six-entry parser and reports what the card
// made of them. Not a test file (the test glob is test/*.test.mjs).
import { readFileSync } from 'node:fs';
import { card } from './helpers.mjs';

const vectors = JSON.parse(readFileSync(process.argv[2], 'utf8'));
const rejected = [];
const noText = new Set();
const classes = {};
for (const v of vectors) {
  const parsed = card.parseObl(v);
  if (!parsed) {
    rejected.push(v);
    continue;
  }
  for (const e of parsed) {
    if (card.own(card.KIND_TEXT, e.k) === undefined) noText.add(e.k);
    classes[e.k] = card.oblKindClass(e.k);
  }
}
process.stdout.write(JSON.stringify({ count: vectors.length, rejected: rejected.slice(0, 5), noText: [...noText], classes }));
