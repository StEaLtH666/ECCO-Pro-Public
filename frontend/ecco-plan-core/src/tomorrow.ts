// Tomorrow's Plan model. Derived only from the inputs passed in; it never invents a number: a missing input is an explicit
// "unknown". Every item carries its state (advice is PROPOSED until something verifies it; a settings-derived item carries the
// weakest state of the fields it came from).
import { norm } from "./time.ts";
import { weakestState } from "./settings.ts";
import type { FieldPath, FieldState, PlanSettings } from "./settings.ts";
import type { ChargePlan } from "./chargePlanner.ts";

export type Confidence = "HIGH" | "MEDIUM" | "LOW" | "INSUFFICIENT";
const CONFIDENCES: readonly string[] = ["HIGH", "MEDIUM", "LOW", "INSUFFICIENT"];

/** An Intelligence advice object. Every field is optional; anything absent or malformed becomes "unknown". */
export interface IntelligenceAdvice {
  expectedImportKwh?: number | null;
  expectedExportKwh?: number | null;
  expectedSolarKwh?: number | null;
  /** Minute of day at which the overnight charge is expected to finish. */
  chargeFinishMin?: number | null;
  confidence?: string | null;
  why?: unknown;
}

export type Item<T> =
  | { known: true; value: T; state: FieldState; origin: "intelligence" | "settings" | "planner"; simulated: boolean }
  | { known: false; reason: string; state: FieldState };

export interface WhyLine {
  origin: "advice" | "settings" | "planner";
  text: string;
}

export interface TomorrowPlan {
  importKwh: Item<number>;
  exportKwh: Item<number>;
  solarKwh: Item<number>;
  /** Minute of day. */
  chargeFinishMin: Item<number>;
  reservePct: Item<number>;
  confidence: { known: boolean; level: Confidence | "UNKNOWN"; state: FieldState };
  why: WhyLine[];
}

export interface TomorrowInput {
  advice: IntelligenceAdvice | null | undefined;
  settings: PlanSettings;
  /** The gentle planner's output for the same settings, if it was run. */
  chargePlan?: ChargePlan | null;
}

function unknown<T>(reason: string): Item<T> {
  return { known: false, reason, state: "PROPOSED" };
}

function adviceNumber(advice: IntelligenceAdvice | null | undefined, k: "expectedImportKwh" | "expectedExportKwh" | "expectedSolarKwh"): Item<number> {
  if (!advice) return unknown("No Intelligence advice is available.");
  const v = advice[k];
  if (v === undefined || v === null) return unknown("Intelligence did not provide this.");
  if (typeof v !== "number" || !Number.isFinite(v) || v < 0) return unknown("Intelligence provided a value that is not a valid amount.");
  return { known: true, value: v, state: "PROPOSED", origin: "intelligence", simulated: false };
}

const CHARGE_FIELDS: readonly FieldPath[] = ["charge.targetSoc", "charge.bufferMin", "charge.powerW", "charge.windowStartMin", "charge.windowEndMin"];

export function buildTomorrowPlan(input: TomorrowInput): TomorrowPlan {
  const { advice, settings, chargePlan } = input;
  const why: WhyLine[] = [];

  let level: Confidence | "UNKNOWN" = "UNKNOWN";
  if (advice && typeof advice.confidence === "string" && CONFIDENCES.includes(advice.confidence)) level = advice.confidence as Confidence;
  const confidence = { known: level !== "UNKNOWN", level, state: "PROPOSED" as FieldState };

  // Charge finish: the advice's own time wins; otherwise a simulated time from the planner; otherwise unknown.
  let chargeFinishMin: Item<number>;
  const adviceFinish = advice?.chargeFinishMin;
  if (typeof adviceFinish === "number" && Number.isFinite(adviceFinish) && adviceFinish >= 0 && adviceFinish < 1440) {
    chargeFinishMin = { known: true, value: Math.round(adviceFinish), state: "PROPOSED", origin: "intelligence", simulated: false };
  } else if (chargePlan && (chargePlan.status === "OK" || chargePlan.status === "BUFFER_TOO_SMALL") && chargePlan.finishNominalMin !== null) {
    const start = settings.fields["charge.windowStartMin"].value;
    chargeFinishMin = { known: true, value: norm(start + chargePlan.finishNominalMin), state: weakestState(settings, CHARGE_FIELDS), origin: "planner", simulated: true };
    if (chargePlan.status === "BUFFER_TOO_SMALL") why.push({ origin: "planner", text: "Buffer too small: the stress case overruns the charge window (simulated, not measured)." });
  } else {
    chargeFinishMin = unknown(chargePlan && chargePlan.status === "NOTHING_TO_CHARGE" ? "No overnight charge is expected to be needed." : "No finish time is available from advice or the planner.");
  }

  const reserveRec = settings.fields["reserve.backupPct"];
  const reservePct: Item<number> = { known: true, value: reserveRec.value, state: reserveRec.state, origin: "settings", simulated: false };

  if (advice && Array.isArray(advice.why)) {
    for (const t of advice.why.slice(0, 8)) if (typeof t === "string" && t.trim()) why.push({ origin: "advice", text: t.trim().slice(0, 200) });
  }
  const t = settings.fields["charge.targetSoc"];
  why.push({ origin: "settings", text: "Charge target " + t.value + " % (" + t.source + ", revision " + t.revision + ", " + t.state + ")." });
  const s = settings.fields["export.stopSoc"];
  why.push({ origin: "settings", text: "Export stops at " + s.value + " % (" + s.source + ", revision " + s.revision + ", " + s.state + ")." });
  why.push({ origin: "settings", text: "Backup reserve " + reserveRec.value + " % (" + reserveRec.source + ", " + reserveRec.state + ")." });
  if (!confidence.known) why.push({ origin: "advice", text: "Confidence is unknown, so nothing here is presented as a firm forecast." });
  else if (level !== "HIGH") why.push({ origin: "advice", text: "Confidence is " + level + ": ECCO holds rather than acts on this forecast." });

  return {
    importKwh: adviceNumber(advice, "expectedImportKwh"),
    exportKwh: adviceNumber(advice, "expectedExportKwh"),
    solarKwh: adviceNumber(advice, "expectedSolarKwh"),
    chargeFinishMin,
    reservePct,
    confidence,
    why,
  };
}
