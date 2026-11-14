// Run by hand to (re)capture the flag-off golden against the PRE-plan card source:
//   git show <pre-plan commit>:frontend/ecco-energy-actions-card/src/ecco-energy-actions-card.ts > src/zz_orig_card.ts
//   node test/support/capture-golden.ts src/zz_orig_card.ts      (then delete src/zz_orig_card.ts)
import { writeFileSync, mkdirSync } from "node:fs";
import { loadCardClass } from "./loadCard.ts";
import { SCENARIOS, renderScenario } from "./scenarios.ts";

const entry = process.argv[2];
if (!entry) throw new Error("pass the pre-plan card source path");
const Card = await loadCardClass(entry);
const out: Record<string, string> = {};
for (const name of Object.keys(SCENARIOS)) out[name] = renderScenario(Card, name);
mkdirSync(new URL("../golden/", import.meta.url), { recursive: true });
writeFileSync(new URL("../golden/flag-off-render.json", import.meta.url), JSON.stringify(out, null, 1) + "\n");
console.log("captured", Object.keys(out).join(", "), Object.values(out).map((s) => s.length).join(" "));
