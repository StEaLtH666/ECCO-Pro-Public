// Gentle overnight charge planner (port of the offline sketch).
//
// Today's firmware fixes ONE rate for the whole Free Power session at START, so the planner returns one fixed rate (the lowest
// 100 W step that finishes by window end minus the finish buffer) and stress-tests it. It never lowers the target to make a plan
// fit: if the buffer is too small it says so. Everything it returns is simulated, not measured.
import { LIMITS } from "./settings.ts";

export const SIMULATED_LABEL = "simulated, not measured";

export interface ChargePlanInput {
  startSocPct: number;
  targetSocPct: number;
  /** Nominal usable capacity in kWh. */
  capacityKwh: number;
  /** Capacity band: the real capacity may be this much higher than nominal (learned capacity drifts). */
  capacityUpPct: number;
  /** Real elapsed minutes of the charge window (use elapsedMinutes() across a clock change). */
  windowMin: number;
  /** Finish-before-end buffer, 0-120 minutes in 5-minute steps. */
  bufferMin: number;
  /** Extra minutes the BMS taper may add at the end. */
  taperMin?: number;
  /** Grid-side to battery-side efficiency. */
  chargeEff?: number;
  roundW?: number;
  minW?: number;
  maxW?: number;
}

export type ChargePlanStatus = "OK" | "NOTHING_TO_CHARGE" | "BUFFER_TOO_SMALL" | "NEEDS_MORE_POWER" | "INVALID";

export interface ChargePlan {
  status: ChargePlanStatus;
  label: typeof SIMULATED_LABEL;
  reasons: string[];
  /** One fixed rate for the whole session (fixed at START by the firmware). Null unless status is OK or BUFFER_TOO_SMALL. */
  rateW: number | null;
  rateFixedAtStart: true;
  targetSocPct: number;
  gridKwh: number;
  finishNominalMin: number | null;
  finishStressMin: number | null;
  /** Minutes before the window ends that the stress case still finishes (negative: overrun). */
  bufferLeftMin: number | null;
  /** When BUFFER_TOO_SMALL: the smallest buffer (5-minute steps) that would absorb the stress case at this rate. */
  suggestedBufferMin: number | null;
}

const ceilStep = (x: number, step: number) => Math.ceil(x / step - 1e-9) * step;

function empty(status: ChargePlanStatus, reasons: string[], input: Partial<ChargePlanInput>, gridKwh = 0): ChargePlan {
  return { status, label: SIMULATED_LABEL, reasons, rateW: null, rateFixedAtStart: true, targetSocPct: input.targetSocPct ?? NaN, gridKwh, finishNominalMin: null, finishStressMin: null, bufferLeftMin: null, suggestedBufferMin: null };
}

export function planGentleCharge(i: ChargePlanInput): ChargePlan {
  const chargeEff = i.chargeEff ?? 0.95;
  const roundW = i.roundW ?? 100;
  const minW = i.minW ?? LIMITS.chargePowerMin;
  const maxW = i.maxW ?? LIMITS.chargePowerMax;
  const taper = i.taperMin ?? 0;
  const nums = [i.startSocPct, i.targetSocPct, i.capacityKwh, i.capacityUpPct, i.windowMin, i.bufferMin, taper, chargeEff];
  if (nums.some((n) => typeof n !== "number" || !Number.isFinite(n))) return empty("INVALID", ["An input is missing or not a number; nothing is planned."], i);
  if (i.capacityKwh <= 0 || i.windowMin <= 0 || chargeEff <= 0 || chargeEff > 1 || i.capacityUpPct < 0 || taper < 0) return empty("INVALID", ["An input is out of range; nothing is planned."], i);
  if (i.startSocPct < 0 || i.startSocPct > 100 || i.targetSocPct < LIMITS.chargeTargetMin || i.targetSocPct > LIMITS.chargeTargetMax) return empty("INVALID", ["A SOC is out of range; nothing is planned."], i);
  if (i.bufferMin < LIMITS.bufferMin || i.bufferMin > LIMITS.bufferMax || i.bufferMin % 5 !== 0) return empty("INVALID", ["The finish buffer must be 0-120 minutes in 5-minute steps."], i);

  const energyKwh = ((i.targetSocPct - i.startSocPct) / 100) * i.capacityKwh;
  if (energyKwh <= 0) return { ...empty("NOTHING_TO_CHARGE", ["The battery is expected to be at or above the target when the window opens."], i), bufferLeftMin: i.windowMin - i.bufferMin };
  const gridKwh = energyKwh / chargeEff;
  const targetMin = i.windowMin - i.bufferMin;
  if (targetMin <= 0) return empty("BUFFER_TOO_SMALL", ["The finish buffer is as long as the window; nothing can be planned inside it. The target is not lowered."], i, gridKwh);

  const rateW = Math.max(minW, ceilStep((gridKwh / (targetMin / 60)) * 1000, roundW));
  if (rateW > maxW) {
    return { ...empty("NEEDS_MORE_POWER", ["Finishing " + i.bufferMin + " minutes early needs " + rateW + " W, above the " + maxW + " W limit. The target is not lowered; shorten the buffer or accept a later finish."], i, gridKwh), suggestedBufferMin: null };
  }
  const finish = (kwh: number) => (kwh / (rateW / 1000)) * 60 + taper;
  const nominal = finish(gridKwh);
  const stress = finish(gridKwh * (1 + i.capacityUpPct / 100));
  const left = i.windowMin - stress;
  const base = { ...empty("OK", [], i, gridKwh), rateW, finishNominalMin: nominal, finishStressMin: stress, bufferLeftMin: left };
  if (stress > i.windowMin + 1e-9) {
    return {
      ...base,
      status: "BUFFER_TOO_SMALL",
      reasons: ["Buffer too small: if the capacity is " + i.capacityUpPct + " % higher than nominal and the taper takes " + taper + " min, the charge overruns the window by about " + Math.ceil(-left) + " min at " + rateW + " W. The target is not lowered."],
      suggestedBufferMin: suggestBuffer(i),
    };
  }
  return { ...base, reasons: ["Lowest 100 W step that finishes by window end minus the buffer, and still finishes inside the window in the stress case."] };
}

/** The smallest larger buffer (a higher rate finishes earlier) whose stress case fits the window, or null if none up to the maximum does. */
function suggestBuffer(i: ChargePlanInput): number | null {
  for (let b = i.bufferMin + 5; b <= LIMITS.bufferMax; b += 5) {
    if (planGentleCharge({ ...i, bufferMin: b }).status === "OK") return b;
  }
  return null;
}
