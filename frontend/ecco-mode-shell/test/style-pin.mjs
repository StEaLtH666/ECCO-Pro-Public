// Prints the pin of the shell stylesheet (not a test file). Review round 3.
//
//   node test/style-pin.mjs            print the pin for the card as it is now
//   node test/style-pin.mjs > test/fixtures/style.pin.json
//
// The pin lists EVERY rule of the stylesheet: its at-rule context, its selectors and each declaration. static.test.mjs compares the stylesheet with the
// file, so adding a selector, adding or changing a declaration, or moving a rule fails the suite until a person has read the new rule and regenerated the
// file. Regenerating is the decision: it shows up as a diff of this one file in the same commit as the stylesheet change. Nothing regenerates it for you,
// and no test or tool in this folder writes it.
import { pathToFileURL } from 'node:url';
import { CARD_PATH } from './helpers.mjs';
import { canonicalSheet } from './css-guard.mjs';

export const PIN_SCHEMA = 'ecco-mode-shell-style-pin/1';

/** The pin text for a stylesheet: one rule per line, so that a change is a readable diff. */
export function pinText(css) {
  const c = canonicalSheet(css);
  if (c.problems.length) throw new Error(`the stylesheet cannot be pinned: ${c.problems.join('; ')}`);
  const lines = c.rules.map((r) => `    ${JSON.stringify(r)}`);
  return `{\n  "schema": ${JSON.stringify(PIN_SCHEMA)},\n  "note": "Every rule of the Production / Geek Mode shell stylesheet, as read by test/css-guard.mjs. Regenerate with: node test/style-pin.mjs > test/fixtures/style.pin.json, and review the diff.",\n  "rules": [\n${lines.join(',\n')}\n  ]\n}\n`;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const { STYLE } = await import(pathToFileURL(CARD_PATH).href);
  process.stdout.write(pinText(STYLE));
}
