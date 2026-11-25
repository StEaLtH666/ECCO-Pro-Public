// Writes test/gentleNightProbe.golden.json from the CURRENT src/gentleNight.ts (one probe key per line). Run it only for a deliberate, reviewed change of
// the night planner's behaviour: the golden is what test/gentleNightMutants.test.ts holds the source and every mutant against. Usage, from the package root:
//   node test/support/writeNightProbeGolden.ts
import { writeFileSync } from "node:fs";
import * as night from "../../src/gentleNight.ts";
import { signature } from "./gentleNightProbe.ts";

const sig = signature(night);
const lines = Object.keys(sig).map((k) => "  " + JSON.stringify(k) + ": " + sig[k]);
writeFileSync(new URL("../gentleNightProbe.golden.json", import.meta.url), "{\n" + lines.join(",\n") + "\n}\n", "utf8");
console.log("wrote " + lines.length + " probe keys");
