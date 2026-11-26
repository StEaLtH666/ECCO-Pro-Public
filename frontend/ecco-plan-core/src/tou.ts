// Derived TOU compiler: the two actions' schedules + the owner's native baseline -> the six native TOU slots.
//
// Deterministic and pure. It returns the INTENDED table and per-slot intended-vs-verified state; it never writes. On any refusal
// the intended table is the owner's baseline unchanged (the explicit "unchanged native fallback"), never a partial or truncated
// table. Assumption flagged for the owner: the Export to Grid action is today a firmware session, not a table slot; here it is
// compiled as a no-grid-charge slot whose target SOC is the Stop SOC and whose power is the export power, so that the
// six-slot budget it would consume is visible. See README.
import { DAY_MIN, GRID_MIN, ORDINARY_DAY, elapsedMinutes, fmt, isClockChangeNight, norm, onGrid, span, touchesChangeHours } from "./time.ts";
import type { ClockDay } from "./time.ts";
import { LIMITS } from "./settings.ts";
import type { FieldState } from "./settings.ts";

export type ChargeSource = "Grid" | "None";

export interface NativeSlot {
  /** Wall-clock start minute, on the 5-minute grid. */
  startMin: number;
  powerW: number;
  targetSoc: number;
  source: ChargeSource;
}

export type ActionKind = "charge" | "export";

export interface DerivedInterval {
  action: ActionKind;
  startMin: number;
  durationMin: number;
  targetSoc: number;
  powerW: number;
}

export interface CompileInput {
  /** The owner's native six-slot table: the fallback for every minute no action derives. */
  baseline: readonly NativeSlot[];
  intervals: readonly DerivedInterval[];
  /** The table as last read back from the inverter (null: not read). */
  observed?: readonly NativeSlot[] | null;
  /** The table ECCO last wrote and verified (null: never). Compared with `observed` to detect a manual TOU edit. */
  lastApplied?: readonly NativeSlot[] | null;
  /** Non-null while any transaction (Free Power, Dump, a slot edit) owns the inverter: the single-writer rule refuses. */
  transactionOwner?: string | null;
  /** From the grid-loss design: anything but an explicit false refuses every export start (fail-safe). */
  controlLocked: boolean;
  day?: ClockDay;
  /** Minimum gap between the end of one action and the start of the other (the end minute counts, so at least 5). */
  handoverGapMin?: number;
}

export type CompileStatus = "OK" | "INFEASIBLE" | "CONFLICT" | "REFUSED";

export type Origin = "derived:charge" | "derived:export" | "native-fallback";

export interface SlotReport {
  index: number;
  intended: NativeSlot;
  origin: Origin;
  observed: NativeSlot | null;
  /** APPLIED_VERIFIED only when the observed slot equals the intended one; PROPOSED when nothing was read; else MISMATCH. */
  state: FieldState;
}

export interface SlotEdit {
  slot: number;
  field: "startMin" | "powerW" | "targetSoc" | "source";
  from: number | string | null;
  to: number | string;
}

export interface IntervalReport {
  action: ActionKind;
  startMin: number;
  wallMin: number;
  elapsedMin: number;
}

export interface CompileResult {
  status: CompileStatus;
  reasons: string[];
  /** Always exactly six slots, always a valid table (baseline unchanged when status is not OK). */
  slots: NativeSlot[];
  slotReports: SlotReport[];
  /** True when the intended table is the owner's baseline unchanged because nothing could be derived. */
  fallback: boolean;
  /** Single-field edits that would turn the observed table (or the baseline if unread) into the intended one. Data only. */
  edits: SlotEdit[];
  intervals: IntervalReport[];
  /** Derived intervals that were dropped with a reason although the rest compiled (for example an export under a lock). */
  refused: { action: ActionKind; reason: string }[];
  /** Slots the derived plan would need before padding; > 6 only when INFEASIBLE. */
  slotsNeeded: number;
  deferredToAfterClockChange: boolean;
}

export type TableCheck = { ok: true } | { ok: false; why: string };

/** A valid native table: six slots, 5-minute grid, one cyclic 24-hour pass in slot order, each at least 5 minutes. */
export function validateTable(table: readonly NativeSlot[] | null | undefined): TableCheck {
  if (!Array.isArray(table) || table.length !== LIMITS.slots) return { ok: false, why: "the table does not have six slots" };
  for (const s of table) {
    if (!s || !onGrid(s.startMin)) return { ok: false, why: "a slot start is unreadable or off the 5-minute grid" };
    if (s.source !== "Grid" && s.source !== "None") return { ok: false, why: "a slot has an unknown charge source" };
    if (!Number.isFinite(s.powerW) || !Number.isFinite(s.targetSoc)) return { ok: false, why: "a slot power or target SOC is unreadable" };
  }
  let total = 0;
  for (let i = 0; i < LIMITS.slots; i++) {
    const a = (table[i] as NativeSlot).startMin;
    const b = (table[(i + 1) % LIMITS.slots] as NativeSlot).startMin;
    const d = span(a, b);
    if (d < LIMITS.minSlotMin) return { ok: false, why: "slot " + (i + 1) + " is shorter than 5 minutes" };
    total += d;
  }
  if (total !== DAY_MIN) return { ok: false, why: "the six starts are not one 24-hour cycle in slot order" };
  return { ok: true };
}

export function sameSlot(a: NativeSlot, b: NativeSlot): boolean {
  return a.startMin === b.startMin && a.powerW === b.powerW && a.targetSoc === b.targetSoc && a.source === b.source;
}

export function sameTable(a: readonly NativeSlot[], b: readonly NativeSlot[]): boolean {
  return a.length === b.length && a.every((s, i) => sameSlot(s, b[i] as NativeSlot));
}

const CELLS = DAY_MIN / GRID_MIN;

interface Attr {
  powerW: number;
  targetSoc: number;
  source: ChargeSource;
  /** the action that produced it, or null for the baseline */
  from: ActionKind | null;
}

const key = (a: Attr) => a.source + "|" + a.powerW + "|" + a.targetSoc;

function cellAttr(baseline: readonly NativeSlot[]): Attr[] {
  const cells: Attr[] = [];
  for (let c = 0; c < CELLS; c++) {
    const t = c * GRID_MIN;
    let hit = baseline[0] as NativeSlot;
    for (let i = 0; i < baseline.length; i++) {
      const s = baseline[i] as NativeSlot;
      const next = baseline[(i + 1) % baseline.length] as NativeSlot;
      if (span(s.startMin, t) < span(s.startMin, next.startMin)) {
        hit = s;
        break;
      }
    }
    cells.push({ powerW: hit.powerW, targetSoc: hit.targetSoc, source: hit.source, from: null });
  }
  return cells;
}

function failResult(input: CompileInput, status: CompileStatus, reasons: string[], extra: Partial<CompileResult> = {}): CompileResult {
  const baseline = input.baseline.map((s) => ({ ...s }));
  return {
    status,
    reasons,
    slots: baseline,
    slotReports: reportSlots(baseline, baseline.map(() => "native-fallback" as Origin), input.observed ?? null),
    fallback: true,
    // No edits on a refusal: never propose restoring the baseline over a manual change.
    edits: [],
    intervals: [],
    refused: [],
    slotsNeeded: 0,
    deferredToAfterClockChange: false,
    ...extra,
  };
}

function reportSlots(slots: readonly NativeSlot[], origins: readonly Origin[], observed: readonly NativeSlot[] | null): SlotReport[] {
  return slots.map((intended, index) => {
    const seen = observed && observed.length === slots.length ? (observed[index] as NativeSlot) : null;
    const state: FieldState = seen === null ? "PROPOSED" : sameSlot(seen, intended) ? "APPLIED_VERIFIED" : "MISMATCH";
    return { index: index + 1, intended: { ...intended }, origin: origins[index] as Origin, observed: seen ? { ...seen } : null, state };
  });
}

export function diffTables(from: readonly NativeSlot[] | null, to: readonly NativeSlot[]): SlotEdit[] {
  const out: SlotEdit[] = [];
  to.forEach((t, i) => {
    const f = from && from.length === to.length ? (from[i] as NativeSlot) : null;
    const fields: SlotEdit["field"][] = ["startMin", "powerW", "targetSoc", "source"];
    for (const field of fields) {
      if (f === null || f[field] !== t[field]) out.push({ slot: i + 1, field, from: f === null ? null : f[field], to: t[field] });
    }
  });
  return out;
}

function attrFor(iv: DerivedInterval): Attr {
  return { powerW: iv.powerW, targetSoc: iv.targetSoc, source: iv.action === "charge" ? "Grid" : "None", from: iv.action };
}

function validateInterval(iv: DerivedInterval): string | null {
  if (iv.action !== "charge" && iv.action !== "export") return "unknown action";
  if (!onGrid(iv.startMin)) return iv.action + " start is not on the 5-minute grid";
  if (!Number.isInteger(iv.durationMin) || iv.durationMin < LIMITS.minSlotMin || iv.durationMin % GRID_MIN !== 0) return iv.action + " duration must be a multiple of 5 minutes, at least 5";
  if (iv.durationMin >= DAY_MIN) return iv.action + " cannot cover the whole day";
  if (iv.action === "export") {
    if (!Number.isInteger(iv.targetSoc) || iv.targetSoc < LIMITS.stopSocMin || iv.targetSoc > LIMITS.stopSocMax) return "export Stop SOC must be " + LIMITS.stopSocMin + "-" + LIMITS.stopSocMax + " %";
    if (iv.powerW < LIMITS.exportPowerMin || iv.powerW > LIMITS.exportPowerMax) return "export power is outside " + LIMITS.exportPowerMin + "-" + LIMITS.exportPowerMax + " W";
  } else {
    if (!Number.isFinite(iv.targetSoc) || iv.targetSoc < LIMITS.chargeTargetMin || iv.targetSoc > LIMITS.chargeTargetMax) return "charge target SOC is outside " + LIMITS.chargeTargetMin + "-" + LIMITS.chargeTargetMax + " %";
    if (iv.powerW < LIMITS.chargePowerMin || iv.powerW > LIMITS.chargePowerMax) return "charge power is outside " + LIMITS.chargePowerMin + "-" + LIMITS.chargePowerMax + " W";
  }
  return null;
}

/** Number of slot differences between two tables at the same indices (used to keep slot numbers stable). */
function distance(a: readonly NativeSlot[], b: readonly NativeSlot[]): number {
  let n = 0;
  for (let i = 0; i < a.length; i++) if (!sameSlot(a[i] as NativeSlot, b[i] as NativeSlot)) n++;
  return n;
}

export function compileTou(input: CompileInput): CompileResult {
  const day = input.day ?? ORDINARY_DAY;
  const gap = Math.max(GRID_MIN, input.handoverGapMin ?? GRID_MIN);

  if (input.transactionOwner) {
    return failResult(input, "REFUSED", ["Single writer: " + input.transactionOwner + " owns the inverter right now; nothing is compiled until it ends and its restore is verified."]);
  }
  const base = validateTable(input.baseline);
  if (!base.ok) return failResult(input, "REFUSED", ["The native baseline is not a valid six-slot day: " + (base as { why: string }).why + "."]);

  // Manual TOU edit detection: the inverter table must equal what ECCO last applied (or the baseline if it never applied).
  if (input.observed) {
    const obs = validateTable(input.observed);
    if (!obs.ok) return failResult(input, "CONFLICT", ["The observed inverter table is not a valid six-slot day: " + (obs as { why: string }).why + "; reconcile before planning."]);
    const expected = input.lastApplied ?? input.baseline;
    if (!sameTable(input.observed, expected)) {
      const d = diffTables(expected, input.observed);
      return failResult(input, "CONFLICT", ["The inverter table differs from " + (input.lastApplied ? "what ECCO last applied" : "the owner's baseline") + " (" + d.length + " field(s), first: slot " + (d[0] as SlotEdit).slot + " " + (d[0] as SlotEdit).field + "). It looks edited outside ECCO; review and adopt it or restore before anything is compiled."]);
    }
  }

  const refused: { action: ActionKind; reason: string }[] = [];
  let intervals = input.intervals.filter((iv) => {
    if (iv.action === "export" && input.controlLocked !== false) {
      refused.push({ action: "export", reason: "Control is locked (grid-loss lock): every export start is refused." });
      return false;
    }
    return true;
  });

  for (const iv of intervals) {
    const bad = validateInterval(iv);
    if (bad) return failResult(input, "REFUSED", ["Invalid derived interval: " + bad + "."], { refused });
  }
  if (intervals.filter((iv) => iv.action === "charge").length > 1 || intervals.filter((iv) => iv.action === "export").length > 1) {
    return failResult(input, "REFUSED", ["Only one charge and one export interval can be derived per cycle."], { refused });
  }

  // Overlap / handover: the end minute of one action counts, so the other must start at least `gap` minutes after it ends.
  const ch = intervals.find((iv) => iv.action === "charge");
  const ex = intervals.find((iv) => iv.action === "export");
  if (ch && ex) {
    const afterExport = span(ex.startMin + ex.durationMin, ch.startMin);
    const afterCharge = span(ch.startMin + ch.durationMin, ex.startMin);
    const overlap = span(ch.startMin, ex.startMin) < ch.durationMin || span(ex.startMin, ch.startMin) < ex.durationMin;
    if (overlap) return failResult(input, "REFUSED", ["The export would overlap the charge window; the firmware refuses an export that touches a charge slot."], { refused });
    if (afterExport < gap || afterCharge < gap) {
      return failResult(input, "REFUSED", ["Fewer than " + gap + " minutes between the export and the charge window; time is needed to restore and verify."], { refused });
    }
  }

  // Clock-change night: derived boundaries in 00:00-03:00 are deferred (export: any minute in that span).
  let deferred = false;
  if (isClockChangeNight(day)) {
    for (const iv of intervals) {
      const end = norm(iv.startMin + iv.durationMin);
      const hits = iv.action === "export" ? touchesChangeHours(iv.startMin, iv.durationMin) : iv.startMin < 180 || end < 180;
      if (hits) deferred = true;
    }
    if (deferred) {
      return failResult(input, "REFUSED", ["Clock-change night: derived changes that start, end or run between 00:00 and 03:00 wait until the night is over; the native table keeps running unchanged."], { refused, deferredToAfterClockChange: true });
    }
  }

  // Overlay onto 5-minute cells, then find the boundaries.
  const cells = cellAttr(input.baseline);
  for (const iv of intervals) {
    const a = attrFor(iv);
    for (let k = 0; k < iv.durationMin; k += GRID_MIN) cells[((iv.startMin + k) / GRID_MIN) % CELLS] = { ...a };
  }
  const starts: number[] = [];
  for (let c = 0; c < CELLS; c++) {
    const prev = cells[(c + CELLS - 1) % CELLS] as Attr;
    if (key(prev) !== key(cells[c] as Attr)) starts.push(c * GRID_MIN);
  }
  if (starts.length === 0) starts.push((input.baseline[0] as NativeSlot).startMin);
  const needed = starts.length;
  if (needed > LIMITS.slots) {
    return failResult(input, "INFEASIBLE", [
      "Six native slots are not enough: this plan needs " + needed + " distinct slots (changes at " + starts.map((m) => fmt(m)).join(", ") + ") and the inverter has exactly " + LIMITS.slots + ". Nothing is truncated; the native table stays as it is.",
    ], { refused, slotsNeeded: needed, intervals: intervalReports(intervals, day) });
  }

  // Pad to six without changing behaviour: first the baseline starts that merging removed, then bisect the longest segment.
  const have = new Set(starts);
  for (const s of input.baseline) {
    if (starts.length >= LIMITS.slots) break;
    if (!have.has(s.startMin)) {
      starts.push(s.startMin);
      have.add(s.startMin);
    }
  }
  starts.sort((a, b) => a - b);
  while (starts.length < LIMITS.slots) {
    let best = -1;
    let bestLen = 0;
    for (let i = 0; i < starts.length; i++) {
      const len = span(starts[i] as number, starts[(i + 1) % starts.length] as number) || DAY_MIN;
      if (len > bestLen) {
        bestLen = len;
        best = i;
      }
    }
    const cut = norm((starts[best] as number) + Math.floor(bestLen / 2 / GRID_MIN) * GRID_MIN);
    starts.push(cut);
    starts.sort((a, b) => a - b);
  }

  const attrAt = (m: number) => cells[m / GRID_MIN] as Attr;
  const built = starts.map((m) => {
    const a = attrAt(m);
    const slot: NativeSlot = { startMin: m, powerW: a.powerW, targetSoc: a.targetSoc, source: a.source };
    return slot;
  });
  const originOf = (m: number, nextM: number): Origin => {
    const len = span(m, nextM) || DAY_MIN;
    for (let k = 0; k < len; k += GRID_MIN) {
      const f = attrAt(norm(m + k)).from;
      if (f) return f === "charge" ? "derived:charge" : "derived:export";
    }
    return "native-fallback";
  };

  // Rotate so slot numbers stay as close to the baseline as possible (fewest single-field edits).
  let bestRot = 0;
  let bestDist = Infinity;
  for (let r = 0; r < LIMITS.slots; r++) {
    const rotated = built.map((_, i) => built[(i + r) % LIMITS.slots] as NativeSlot);
    const d = distance(rotated, input.baseline);
    if (d < bestDist) {
      bestDist = d;
      bestRot = r;
    }
  }
  const slots = built.map((_, i) => ({ ...(built[(i + bestRot) % LIMITS.slots] as NativeSlot) }));
  const origins = built.map((_, i) => {
    const j = (i + bestRot) % LIMITS.slots;
    return originOf((built[j] as NativeSlot).startMin, (built[(j + 1) % LIMITS.slots] as NativeSlot).startMin);
  });

  const final = validateTable(slots);
  if (!final.ok) {
    // Defensive: never emit an invalid table.
    return failResult(input, "REFUSED", ["Internal check failed (" + (final as { why: string }).why + "); the native table stays as it is."], { refused });
  }
  const fallback = sameTable(slots, input.baseline);
  return {
    status: "OK",
    reasons: refused.map((r) => r.reason),
    slots,
    slotReports: reportSlots(slots, origins, input.observed ?? null),
    fallback,
    edits: diffTables(input.observed ?? input.baseline, slots),
    intervals: intervalReports(intervals, day),
    refused,
    slotsNeeded: needed,
    deferredToAfterClockChange: false,
  };
}

function intervalReports(intervals: readonly DerivedInterval[], day: ClockDay): IntervalReport[] {
  return intervals.map((iv) => ({ action: iv.action, startMin: iv.startMin, wallMin: iv.durationMin, elapsedMin: elapsedMinutes(iv.startMin, iv.durationMin, day) }));
}
