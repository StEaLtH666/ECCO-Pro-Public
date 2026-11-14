// Run by hand to (re)capture the flag-off golden: node test/support/capture-golden.ts   (only against the PRE-plan card source).
import { writeFileSync, mkdirSync } from "node:fs";
import { loadCardClass } from "./loadCard.ts";
import { SCENARIOS, renderScenario } from "./scenarios.ts";

const Card = await loadCardClass();
const out: Record<string, string> = {};
for (const name of Object.keys(SCENARIOS)) out[name] = renderScenario(Card, name);
mkdirSync(new URL("../golden/", import.meta.url), { recursive: true });
writeFileSync(new URL("../golden/flag-off-render.json", import.meta.url), JSON.stringify(out, null, 1) + "\n");
console.log("captured", Object.keys(out).join(", "), Object.values(out).map((s) => s.length).join(" "));
