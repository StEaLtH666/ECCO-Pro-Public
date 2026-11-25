// Safety guards as code. Every function returns data; none can write anything.
import { LIMITS } from "./settings.ts";
import type { FieldRecord } from "./settings.ts";
import { validateTable } from "./tou.ts";
import type { CompileResult } from "./tou.ts";

export interface Verdict {
  allowed: boolean;
  reasons: string[];
}

/** A Stop SOC is valid only as an integer 10-90 %. Anything else is refused, never clamped. */
export function checkStopSoc(v: unknown): Verdict {
  if (typeof v !== "number" || !Number.isInteger(v) || v < LIMITS.stopSocMin || v > LIMITS.stopSocMax) {
    return { allowed: false, reasons: ["Stop SOC must be a whole number from " + LIMITS.stopSocMin + " to " + LIMITS.stopSocMax + " %."] };
  }
  return { allowed: true, reasons: [] };
}

export interface ExportStartContext {
  /** From the grid-loss design. Fail-safe: only an explicit false allows a start; true, missing or any other value refuses. */
  controlLocked: boolean;
  transactionOwner?: string | null;
  stopSoc: number;
  /** The enforced reserve; the export may not end below it. */
  backupReservePct: number;
}

/** Whether a plan may START an export now. Refuses every start while locked. */
export function canStartExport(ctx: ExportStartContext): Verdict {
  const reasons: string[] = [];
  if (ctx.controlLocked !== false) reasons.push("Control is locked: every export start is refused until the owner re-enables it.");
  if (ctx.transactionOwner) reasons.push("Single writer: " + ctx.transactionOwner + " owns the inverter.");
  const stop = checkStopSoc(ctx.stopSoc);
  if (!stop.allowed) reasons.push(...stop.reasons);
  else if (ctx.stopSoc < ctx.backupReservePct) reasons.push("Stop SOC " + ctx.stopSoc + " % is below the enforced backup reserve of " + ctx.backupReservePct + " %.");
  return { allowed: reasons.length === 0, reasons };
}

/** An APPLIED_VERIFIED claim is honest only with a matching read-back. */
export function appliedClaimIsHonest(rec: Pick<FieldRecord, "state" | "value" | "observed">): boolean {
  return rec.state !== "APPLIED_VERIFIED" || (rec.observed !== null && rec.observed === rec.value);
}

/** A reserve may only be raised by an override. */
export function isRaiseOnly(before: number, after: number): boolean {
  return after >= before;
}

/** Invariants every compile result must satisfy. Returns the list of violations (empty when sound). */
export function compileInvariantViolations(r: CompileResult): string[] {
  const v: string[] = [];
  if (r.slots.length > LIMITS.slots) v.push("more than six slots");
  const t = validateTable(r.slots);
  if (!t.ok) v.push("invalid table: " + (t as { why: string }).why);
  if (r.status !== "OK" && !r.fallback) v.push("a refused compile must fall back to the unchanged native baseline");
  if (r.slotReports.length !== r.slots.length) v.push("slot report count differs");
  for (const s of r.slotReports) {
    if (s.state === "APPLIED_VERIFIED" && (s.observed === null)) v.push("slot " + s.index + " claims verified without a read-back");
  }
  return v;
}
