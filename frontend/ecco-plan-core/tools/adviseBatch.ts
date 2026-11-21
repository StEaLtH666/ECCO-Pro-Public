// Offline batch runner for the Gentle replay tool (intelligence/tools/gentle_replay.py). READ ONLY: it reads one JSON document from standard input,
// asks the pure `adviseGentleRate` (src/gentleAdvice.ts) one question per case and writes one JSON document to standard output. It opens no file, makes no
// network call, calls no service and keeps nothing between runs. It lives outside `src/` because it uses standard input and output, which the package
// sources must never touch.
//
//   in : { "cases": [ { "id": "any string", "input": <GentleAdviceInput> }, ... ] }
//   out: { "results": [ { "id", "advice", "reason", "outcome", "status", "rateW", "rateAmps", "neededW", "minRateW", "safeMaxW", "limitedBy",
//                         "deadlineInMin", "finishInMin", "marginMin", "targetWillBeMissed", "degraded", "codes", "summary" } | { "id", "error" } ] }
//
// Run with Node 22.18+ or 24 (type stripping): node frontend/ecco-plan-core/tools/adviseBatch.ts < cases.json
import { readFileSync } from "node:fs";
import { adviseGentleRate } from "../src/gentleAdvice.ts";
import type { GentleAdviceInput } from "../src/gentleAdvice.ts";

const MAX_CASES = 20000;

interface CaseIn {
  id: unknown;
  input: unknown;
}

function fail(message: string): never {
  process.stderr.write("adviseBatch: " + message + "\n");
  process.exit(2);
}

let doc: { cases?: unknown };
try {
  doc = JSON.parse(readFileSync(0, "utf8")) as { cases?: unknown };
} catch (e) {
  fail("the input is not valid JSON: " + (e instanceof Error ? e.message : String(e)));
}
if (doc === null || typeof doc !== "object" || !Array.isArray(doc.cases)) fail('the input must be {"cases": [...]}');
const cases = doc.cases as CaseIn[];
if (cases.length > MAX_CASES) fail("too many cases (" + cases.length + ", the limit is " + MAX_CASES + ")");

const results: Array<Record<string, unknown>> = [];
for (const c of cases) {
  const id = c !== null && typeof c === "object" ? c.id : undefined;
  try {
    const a = adviseGentleRate((c as CaseIn).input as GentleAdviceInput);
    results.push({
      id,
      advice: a.advice,
      reason: a.reason,
      outcome: a.outcome,
      status: a.status,
      rateW: a.rateW,
      rateAmps: a.rateAmps,
      neededW: a.neededW,
      minRateW: a.minRateW,
      safeMaxW: a.safeMaxW,
      limitedBy: a.limitedBy,
      deadlineInMin: a.deadlineInMin,
      finishInMin: a.finishInMin,
      marginMin: a.marginMin,
      targetWillBeMissed: a.targetWillBeMissed,
      degraded: a.degraded,
      codes: a.codes,
      summary: a.summary,
    });
  } catch (e) {
    results.push({ id, error: e instanceof Error ? e.message : String(e) });
  }
}
process.stdout.write(JSON.stringify({ results }) + "\n");
